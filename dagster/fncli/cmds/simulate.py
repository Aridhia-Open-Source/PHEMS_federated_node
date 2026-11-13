"""
A multi-provider simulation on the dev cluster (see fncli.simulation): several projects over two git providers, three
trigger repositories and two results repositories. Pull requests are merged in the trigger repositories at the same time,
the sensors do the rest, and the end state is checked per project and repository.

Both providers are the cluster's one Gitea, under two names: the second is a Kubernetes ExternalName service (`gitea-b`)
this module creates, so the providers' uris stay unique.

Every command takes --context (bootstrap/context.yaml): the node it works on. The node must already have its one Gitea
provider (`fncli apply -f examples/globals-gitea.yaml`), whose address the simulation's providers are made from.

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
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import click
from kubernetes import client as k8s
from kubernetes.client.rest import ApiException
from kubernetes.config import load_kube_config

from fncli import simulation
from fncli.backend import FncliBackendAPI
from fncli.cmds.common import (
    DagsterConfig,
    GiteaConfig,
    ProjectConfig,
    ResultsRepoConfig,
    TriggerRepoConfig,
    build_gitea_api,
)
from fncli.cmds.nodefile import context_option, open_target
from fncli.cmds.pr import DEFAULT_TRIGGER_FILE, file_for, load_trigger, new_branch_name
from fncli.cmds.project import init_backend_project
from fncli.cmds.repository import init_backend_results_repo, init_backend_trigger_repo, init_gitea_repo
from fncli.cmds.secret import init_git_secret, verify_gitea_accepts_bearer_token
from fncli.cmds.sensor import ALL_SENSORS
from fncli.cmds.state import snapshot
from fncli.nodefile.loader import Context
from fncli.sensors import DagsterAPI

logger = logging.getLogger("simulate")

LAYOUT = simulation.DEFAULT_LAYOUT
ALIAS_SERVICE = "gitea-b"
STATE_FILE = Path("artifacts/simulation/last-run.json")
POLL_SECONDS = 5


# --- Names and configs ------------------------------------------------------------------------


@dataclass
class Target:
    """What the simulation works on: the context's node, a client for it, and the node's Gitea as its one gitea provider has it"""

    context: Context
    backend_api: FncliBackendAPI
    gitea_uri: str
    gitea_api_uri: str

    @property
    def gitea_admin_user(self) -> str:
        return self.context.node.gitea_admin_user

    def gitea_config(self) -> GiteaConfig:
        return GiteaConfig(node=self.context.node, gitea_url=self.gitea_uri)


def open_simulation(context: Context) -> Target:
    """Opens the node, and takes the Gitea from the node's one gitea provider, which `fncli apply` of a globals file made"""
    backend_api = open_target(context)
    providers = [provider for provider in backend_api.get_git_providers() if provider.type == "gitea"]
    if len(providers) != 1:
        raise click.ClickException(
            f"The simulation needs the node to have exactly one gitea provider, it has {len(providers)}: "
            "fncli apply -f examples/globals-gitea.yaml"
        )
    return Target(context, backend_api, providers[0].uri, providers[0].api_uri)


def provider_hosts(target: Target) -> dict[str, str]:
    """The host[:port] of each provider: "a" is the Gitea as the test project reaches it, "b" the alias service."""
    host = urlparse(target.gitea_api_uri).netloc
    name, dot, rest = host.partition(".")
    if not dot:
        raise click.ClickException(
            f"The node's gitea provider must have an in-cluster api_uri like http://gitea.fn.svc:4000/api/v1, has {target.gitea_api_uri!r}"
        )
    return {"a": host, "b": f"{ALIAS_SERVICE}.{rest}"}


def repo_fields(target: Target, repo: str, provider: str) -> dict:
    """What every config of a repository carries: its uri and api uri on its provider."""
    base = urlparse(target.gitea_api_uri)
    host = provider_hosts(target)[provider]
    return {
        "node": target.context.node,
        "project_name": "simulation",  # required by the config, the projects are named by the layout
        "repo": repo,
        "repo_uri": f"{base.scheme}://{host}/{target.gitea_admin_user}/{repo}",
        "gitea_url": f"{base.scheme}://{host}",
        "gitea_api_uri": base._replace(netloc=host).geturl(),
        "token_name": repo,  # Gitea tells tokens apart by name
    }


def trigger_config(target: Target, repo: str) -> TriggerRepoConfig:
    return TriggerRepoConfig(**repo_fields(target, repo, LAYOUT.trigger_repos[repo]), watch_dir="specs/")


def results_config(target: Target, repo: str) -> ResultsRepoConfig:
    return ResultsRepoConfig(**repo_fields(target, repo, LAYOUT.results_repos[repo]), target_dir="results/")


# --- The alias service ------------------------------------------------------------------------


def apply_alias(target: Target):
    """A Kubernetes ExternalName service so a second host name reaches the same Gitea."""
    namespace = target.gitea_config().namespace
    external_name = provider_hosts(target)["a"].split(":")[0] + ".cluster.local"
    body = k8s.V1Service(
        metadata=k8s.V1ObjectMeta(name=ALIAS_SERVICE, namespace=namespace, labels={"app": "fncli-simulation"}),
        spec=k8s.V1ServiceSpec(type="ExternalName", external_name=external_name),
    )
    load_kube_config()
    api = k8s.CoreV1Api()
    try:
        api.create_namespaced_service(namespace, body)
    except ApiException as error:
        if error.status != 409:
            raise
        api.patch_namespaced_service(ALIAS_SERVICE, namespace, body)
    logger.info(f"Alias service {ALIAS_SERVICE}.{namespace} -> {external_name}")


def delete_alias(target: Target):
    load_kube_config()
    try:
        k8s.CoreV1Api().delete_namespaced_service(ALIAS_SERVICE, target.gitea_config().namespace)
        logger.info(f"Deleted alias service {ALIAS_SERVICE}")
    except ApiException as error:
        if error.status != 404:
            raise


# --- Setup and teardown -----------------------------------------------------------------------


def setup(target: Target):
    backend_api = target.backend_api
    gitea_api = build_gitea_api(target.gitea_config())
    apply_alias(target)

    default_branch = {}
    for repo in LAYOUT.trigger_repos:
        config = trigger_config(target, repo)
        gitea_repo = init_gitea_repo(config, gitea_api)
        default_branch[repo] = gitea_repo["default_branch"]
        verify_gitea_accepts_bearer_token(config, init_git_secret(config, gitea_api, backend_api), gitea_repo)
    for repo in LAYOUT.results_repos:
        config = results_config(target, repo)
        default_branch[repo] = init_gitea_repo(config, gitea_api)["default_branch"]
        init_git_secret(config, gitea_api, backend_api)

    for name, spec in LAYOUT.projects.items():
        project = init_backend_project(ProjectConfig(node=target.context.node, project_name=name), backend_api)
        for repo in spec["triggers"]:
            init_backend_trigger_repo(trigger_config(target, repo), backend_api, project, default_branch[repo])
        init_backend_results_repo(
            results_config(target, spec["results"]), backend_api, project, default_branch[spec["results"]]
        )
        backend_api.patch_project(project.id, {"enabled": True})  # new projects start disabled
        logger.info(f"Project {name} ready")


def teardown(target: Target):
    backend_api = target.backend_api
    gitea_api = build_gitea_api(target.gitea_config())
    for name in LAYOUT.projects:
        project = backend_api.find_project(name)
        if project:
            backend_api.delete_project(project.id)
            logger.info(f"Deleted project {name}")
    providers = set()
    for repo in LAYOUT.trigger_repos:
        config = trigger_config(target, repo)
        providers.add(config.provider_uri)
        found = backend_api.find_trigger_repository(config.repo_uri)
        if found:
            backend_api.delete_repository(found.id)
    for repo in LAYOUT.results_repos:
        config = results_config(target, repo)
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
        config = trigger_config(target, repo) if repo in LAYOUT.trigger_repos else results_config(target, repo)
        backend_api.delete_secret(config.secret_label)
        gitea_api.delete_token(config.token_name)
        gitea_api.delete_repo(repo)
    delete_alias(target)
    STATE_FILE.unlink(missing_ok=True)


# --- The run ----------------------------------------------------------------------------------


def merge_pull_requests(target: Target, repo: str, kinds: list[str], seed: int) -> list[dict]:
    """Open and merge one pull request of each kind in a trigger repository, one after the other."""
    rng = random.Random(f"{seed}-{repo}")
    config = trigger_config(target, repo)
    trigger = load_trigger(DEFAULT_TRIGGER_FILE)
    gitea_api = build_gitea_api(target.gitea_config())  # one client per thread
    base = gitea_api.get_or_create_repo(repo)["default_branch"]
    merged = []
    for kind in kinds:
        time.sleep(rng.uniform(0, 1.5))  # interleave the repositories
        branch = new_branch_name()
        gitea_api.create_branch(config.repo_path, branch, base)
        path, content = file_for(config, branch, kind, trigger)
        gitea_api.create_file(config.repo_path, path, content, message=f"Add {path}", branch=branch)
        pr = gitea_api.create_pull_request(config.repo_path, branch, base, f"{kind} {branch}", f"A {kind} pull request, from the simulation")
        gitea_api.merge_pull_request(config.repo_path, pr["number"])
        merged.append({"number": pr["number"], "kind": kind})
        logger.info(f"{repo}: merged #{pr['number']} ({kind})")
    return merged


def snapshots(target: Target) -> dict[str, dict]:
    return {name: snapshot(target.backend_api, name) for name in LAYOUT.projects}


def results_titles(target: Target) -> dict[str, list[str]]:
    """The titles of every pull request (open, merged or closed) of each results repository, from Gitea."""
    gitea_api = build_gitea_api(target.gitea_config())
    admin = target.gitea_admin_user
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


def finish(target: Target, merged: dict, timeout: int) -> int:
    """Wait until the sensors have settled every pull request, then check. Returns the number of problems."""
    deadline = time.monotonic() + timeout
    last = None
    while True:
        current = snapshots(target)
        waiting = simulation.pending(LAYOUT, merged, current)
        if waiting != last:
            logger.info(f"Waiting for {len(waiting)}: {waiting[:3]}")
            last = waiting
        if not waiting or time.monotonic() >= deadline:
            break
        time.sleep(POLL_SECONDS)
    problems = simulation.check(LAYOUT, merged, current, results_titles(target), target.gitea_admin_user)
    problems += [f"not settled after {timeout}s: {item}" for item in waiting]
    report = Path("artifacts/simulation") / f"report-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"merged": merged, "problems": problems, "snapshots": current}, indent=2))
    for problem in problems:
        click.echo(f"PROBLEM {problem}")
    click.echo(f"{'FAIL' if problems else 'OK'}: {len(problems)} problem(s); full state in {report}")
    return len(problems)


@click.command("simulate-setup")
@context_option
def simulate_setup_command(context):
    """Create the simulation: alias service, Gitea repos and tokens, two providers, repositories and four projects."""
    setup(open_simulation(context))


@click.command("simulate-run")
@click.option("--seed", default=1, show_default=True, help="Seeds the kinds of the pull requests.")
@click.option("--prs-per-repo", default=6, show_default=True, help="Pull requests merged in each trigger repository.")
@click.option("--timeout", default=900, show_default=True, help="Seconds to wait for the sensors to settle everything.")
@context_option
def simulate_run_command(seed, prs_per_repo, timeout, context):
    """Start the sensors, merge the planned pull requests in all trigger repositories at once, wait, and check."""
    target = open_simulation(context)
    dagster_api = DagsterAPI(DagsterConfig().dagster_url)
    for name in ALL_SENSORS:
        dagster_api.start_sensor(name)
    plan = simulation.make_plan(LAYOUT, seed, prs_per_repo)
    logger.info(f"Plan (seed {seed}): {plan}")
    with ThreadPoolExecutor(max_workers=len(plan)) as pool:
        futures = {repo: pool.submit(merge_pull_requests, target, repo, kinds, seed) for repo, kinds in plan.items()}
        merged = {repo: future.result() for repo, future in futures.items()}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(merged, indent=2))
    if finish(target, merged, timeout):
        raise click.exceptions.Exit(1)


@click.command("simulate-check")
@click.option("--timeout", default=0, show_default=True, help="Seconds to wait for the sensors to settle first.")
@context_option
def simulate_check_command(timeout, context):
    """Check the end state again against the last run's merged pull requests."""
    if not STATE_FILE.exists():
        raise click.ClickException(f"No {STATE_FILE}: run simulate-run first")
    if finish(open_simulation(context), json.loads(STATE_FILE.read_text()), timeout):
        raise click.exceptions.Exit(1)


@click.command("simulate-teardown")
@click.confirmation_option("-y", "--yes", prompt="Delete the simulation's projects, repositories, secrets and Gitea repos?")
@context_option
def simulate_teardown_command(context):
    """Remove everything the simulation made."""
    teardown(open_simulation(context))


COMMANDS = [simulate_setup_command, simulate_run_command, simulate_check_command, simulate_teardown_command]
