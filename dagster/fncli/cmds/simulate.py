"""
A multi-provider simulation on the dev cluster (see fncli.simulation): several projects over two git providers, three
trigger repositories and two results repositories. Pull requests are merged in the trigger repositories at the same time,
the sensors do the rest, and the end state is checked per project and repository.

Both providers are the cluster's one Gitea, under two names: the second is a Kubernetes ExternalName service (`gitea-b`)
this module creates, so the providers' uris stay unique. Not run in the cloud session that wrote it (no cluster there).

    fncli simulate-setup        # the alias service, Gitea repos, tokens, providers, repositories and projects
    fncli simulate-run          # start the sensors, merge the pull requests, wait for the sensors, check
    fncli simulate-check        # check again, from the last run's plan
    fncli simulate-teardown     # remove all of it
"""

import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import click
from pydantic import Field
from kubernetes import client as k8s
from kubernetes.client.rest import ApiException
from kubernetes.config import load_kube_config

from app.config import EnvConfig
from fncli import simulation
from fncli.cmds.common import (
    BackendConfig,
    DagsterConfig,
    GiteaConfig,
    ProjectConfig,
    ResultsRepoConfig,
    TriggerRepoConfig,
    build_backend_api,
    build_gitea_api,
)
from fncli.cmds.pr import PrConfig, file_for, new_branch_name
from fncli.cmds.project import init_backend_project
from fncli.cmds.repository import init_backend_results_repo, init_backend_trigger_repo, init_gitea_repo
from fncli.cmds.secret import init_git_secret, verify_gitea_accepts_bearer_token
from fncli.cmds.sensor import ALL_SENSORS
from fncli.cmds.state import snapshot
from fncli.sensors import DagsterAPI

logger = logging.getLogger("simulate")

LAYOUT = simulation.DEFAULT_LAYOUT
ALIAS_SERVICE = "gitea-b"
STATE_FILE = Path("artifacts/simulation/last-run.json")
POLL_SECONDS = 5


# --- Names and configs ------------------------------------------------------------------------


class SimulationConfig(EnvConfig):
    gitea_api_uri: str = Field(default="", alias="GITEA_API_URI")


def provider_hosts() -> dict[str, str]:
    """The host[:port] of each provider: "a" is the Gitea as the test project reaches it, "b" the alias service."""
    api_uri = SimulationConfig().gitea_api_uri
    host = urlparse(api_uri).netloc
    name, dot, rest = host.partition(".")
    if not api_uri or not dot:
        raise click.ClickException(f"GITEA_API_URI must be an in-cluster address like http://gitea.fn.svc:4000/api/v1, is {api_uri!r}")
    return {"a": host, "b": f"{ALIAS_SERVICE}.{rest}"}


def repo_fields(repo: str, provider: str) -> dict:
    """What every config of a repository carries: its uri and api uri on its provider."""
    base = urlparse(SimulationConfig().gitea_api_uri)
    host = provider_hosts()[provider]
    admin = GiteaConfig().gitea_admin_user
    return {
        "project_name": "simulation",  # required by the config, the projects are named by the layout
        "repo": repo,
        "repo_uri": f"{base.scheme}://{host}/{admin}/{repo}",
        "gitea_api_uri": base._replace(netloc=host).geturl(),
        "token_name": repo,  # Gitea tells tokens apart by name
    }


def trigger_config(repo: str) -> TriggerRepoConfig:
    return TriggerRepoConfig(**repo_fields(repo, LAYOUT.trigger_repos[repo]), watch_dir="specs/")


def results_config(repo: str) -> ResultsRepoConfig:
    return ResultsRepoConfig(**repo_fields(repo, LAYOUT.results_repos[repo]), target_dir="results/")


def pr_config(repo: str) -> PrConfig:
    return PrConfig(**repo_fields(repo, LAYOUT.trigger_repos[repo]), watch_dir="specs/")


# --- The alias service ------------------------------------------------------------------------


def apply_alias():
    """A Kubernetes ExternalName service so a second host name reaches the same Gitea."""
    namespace = GiteaConfig().namespace
    target = provider_hosts()["a"].split(":")[0] + ".cluster.local"
    body = k8s.V1Service(
        metadata=k8s.V1ObjectMeta(name=ALIAS_SERVICE, namespace=namespace, labels={"app": "fncli-simulation"}),
        spec=k8s.V1ServiceSpec(type="ExternalName", external_name=target),
    )
    load_kube_config()
    api = k8s.CoreV1Api()
    try:
        api.create_namespaced_service(namespace, body)
    except ApiException as error:
        if error.status != 409:
            raise
        api.patch_namespaced_service(ALIAS_SERVICE, namespace, body)
    logger.info(f"Alias service {ALIAS_SERVICE}.{namespace} -> {target}")


def delete_alias():
    load_kube_config()
    try:
        k8s.CoreV1Api().delete_namespaced_service(ALIAS_SERVICE, GiteaConfig().namespace)
        logger.info(f"Deleted alias service {ALIAS_SERVICE}")
    except ApiException as error:
        if error.status != 404:
            raise


# --- Setup and teardown -----------------------------------------------------------------------


def setup():
    backend_api = build_backend_api(BackendConfig())
    gitea_api = build_gitea_api(GiteaConfig())
    apply_alias()

    default_branch = {}
    for repo in LAYOUT.trigger_repos:
        config = trigger_config(repo)
        gitea_repo = init_gitea_repo(config, gitea_api)
        default_branch[repo] = gitea_repo["default_branch"]
        verify_gitea_accepts_bearer_token(config, init_git_secret(config, gitea_api, backend_api), gitea_repo)
    for repo in LAYOUT.results_repos:
        config = results_config(repo)
        init_gitea_repo(config, gitea_api)
        init_git_secret(config, gitea_api, backend_api)

    for name, spec in LAYOUT.projects.items():
        project = init_backend_project(ProjectConfig(project_name=name), backend_api)
        for repo in spec["triggers"]:
            init_backend_trigger_repo(trigger_config(repo), backend_api, project, default_branch[repo])
        init_backend_results_repo(results_config(spec["results"]), backend_api, project)
        backend_api.patch_project(project.id, {"enabled": True, "locked": False})  # new projects start locked
        logger.info(f"Project {name} ready")


def teardown():
    backend_api = build_backend_api(BackendConfig())
    gitea_api = build_gitea_api(GiteaConfig())
    for name in LAYOUT.projects:
        project = backend_api.find_project(name)
        if project:
            backend_api.delete_project(project.id)
            logger.info(f"Deleted project {name}")
    providers = set()
    for repo in LAYOUT.trigger_repos:
        config = trigger_config(repo)
        providers.add(config.provider_uri)
        found = backend_api.find_trigger_repository(config.repo_uri)
        if found:
            backend_api.delete_repository(found.id)
    for repo in LAYOUT.results_repos:
        config = results_config(repo)
        providers.add(config.provider_uri)
        found = backend_api.find_results_repository(config.repo_uri)
        if found:
            backend_api.delete_results_repository(found.id)
    in_use = {r.provider.id for r in backend_api.get_trigger_repositories() + backend_api.get_results_repositories()}
    for uri in sorted(providers):
        provider = backend_api.find_git_provider(uri)
        if provider and provider.id not in in_use:
            backend_api.delete_git_provider(provider.id)
            logger.info(f"Deleted provider {provider.name}")
    for repo in [*LAYOUT.trigger_repos, *LAYOUT.results_repos]:
        config = trigger_config(repo) if repo in LAYOUT.trigger_repos else results_config(repo)
        backend_api.delete_secret(config.secret_label)
        gitea_api.delete_token(config.token_name)
        gitea_api.delete_repo(repo)
    delete_alias()
    STATE_FILE.unlink(missing_ok=True)


# --- The run ----------------------------------------------------------------------------------


def merge_pull_requests(repo: str, kinds: list[str], seed: int) -> list[dict]:
    """Open and merge one pull request of each kind in a trigger repository, one after the other."""
    rng = random.Random(f"{seed}-{repo}")
    config = pr_config(repo)
    gitea_api = build_gitea_api(GiteaConfig())  # one client per thread
    base = gitea_api.get_or_create_repo(repo)["default_branch"]
    merged = []
    for kind in kinds:
        time.sleep(rng.uniform(0, 1.5))  # interleave the repositories
        branch = new_branch_name()
        gitea_api.create_branch(config.repo_path, branch, base)
        path, content = file_for(config, branch, kind)
        gitea_api.create_file(config.repo_path, path, content, message=f"Add {path}", branch=branch)
        pr = gitea_api.create_pull_request(config.repo_path, branch, base, f"{kind} {branch}", f"A {kind} pull request, from the simulation")
        gitea_api.merge_pull_request(config.repo_path, pr["number"])
        merged.append({"number": pr["number"], "kind": kind})
        logger.info(f"{repo}: merged #{pr['number']} ({kind})")
    return merged


def snapshots() -> dict[str, dict]:
    backend_api = build_backend_api(BackendConfig())
    return {name: snapshot(backend_api, name) for name in LAYOUT.projects}


def results_titles() -> dict[str, list[str]]:
    """The titles of every pull request (open, merged or closed) of each results repository, from Gitea."""
    gitea_api = build_gitea_api(GiteaConfig())
    admin = GiteaConfig().gitea_admin_user
    titles = {}
    for repo in LAYOUT.results_repos:
        titles[repo], page = [], 1
        while True:
            batch = gitea_api.client.request(
                "GET", f"repos/{admin}/{repo}/pulls", params={"state": "all", "limit": 50, "page": page}
            ).json()
            titles[repo] += [pr["title"] for pr in batch]
            if len(batch) < 50:
                break
            page += 1
    return titles


def finish(merged: dict, timeout: int) -> int:
    """Wait until the sensors have settled every pull request, then check. Returns the number of problems."""
    deadline = time.monotonic() + timeout
    last = None
    while True:
        current = snapshots()
        waiting = simulation.pending(LAYOUT, merged, current)
        if waiting != last:
            logger.info(f"Waiting for {len(waiting)}: {waiting[:3]}")
            last = waiting
        if not waiting or time.monotonic() >= deadline:
            break
        time.sleep(POLL_SECONDS)
    problems = simulation.check(LAYOUT, merged, current, results_titles(), GiteaConfig().gitea_admin_user)
    problems += [f"not settled after {timeout}s: {item}" for item in waiting]
    report = Path("artifacts/simulation") / f"report-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"merged": merged, "problems": problems, "snapshots": current}, indent=2))
    for problem in problems:
        click.echo(f"PROBLEM {problem}")
    click.echo(f"{'FAIL' if problems else 'OK'}: {len(problems)} problem(s); full state in {report}")
    return len(problems)


@click.command("simulate-setup")
def simulate_setup_command():
    """Create the simulation: alias service, Gitea repos and tokens, two providers, repositories and four projects."""
    setup()


@click.command("simulate-run")
@click.option("--seed", default=1, show_default=True, help="Seeds the kinds of the pull requests.")
@click.option("--prs-per-repo", default=6, show_default=True, help="Pull requests merged in each trigger repository.")
@click.option("--timeout", default=900, show_default=True, help="Seconds to wait for the sensors to settle everything.")
def simulate_run_command(seed, prs_per_repo, timeout):
    """Start the sensors, merge the planned pull requests in all trigger repositories at once, wait, and check."""
    dagster_api = DagsterAPI(DagsterConfig().dagster_url)
    for name in ALL_SENSORS:  # run-status sensors before the launcher
        dagster_api.start_sensor(name)
    plan = simulation.make_plan(LAYOUT, seed, prs_per_repo)
    logger.info(f"Plan (seed {seed}): {plan}")
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:
        futures = {repo: pool.submit(merge_pull_requests, repo, kinds, seed) for repo, kinds in plan.items()}
        merged = {repo: future.result() for repo, future in futures.items()}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(merged, indent=2))
    if finish(merged, timeout):
        raise click.exceptions.Exit(1)


@click.command("simulate-check")
@click.option("--timeout", default=0, show_default=True, help="Seconds to wait for the sensors to settle first.")
def simulate_check_command(timeout):
    """Check the end state again against the last run's merged pull requests."""
    if not STATE_FILE.exists():
        raise click.ClickException(f"No {STATE_FILE}: run simulate-run first")
    if finish(json.loads(STATE_FILE.read_text()), timeout):
        raise click.exceptions.Exit(1)


@click.command("simulate-teardown")
@click.confirmation_option("-y", "--yes", prompt="Delete the simulation's projects, repositories, secrets and Gitea repos?")
def simulate_teardown_command():
    """Remove everything the simulation made."""
    teardown()


COMMANDS = [simulate_setup_command, simulate_run_command, simulate_check_command, simulate_teardown_command]
