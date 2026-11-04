"""
`fncli demo` sets up everything needed to watch a Gitea repo, one confirmed step at a time,
then proves it works. Each step is one of the step commands, run in this process with the
demo's own names from `.demo.env` (repo root), which win over `.dev.env`.
"""

import json
import os
import time
from collections import Counter
from contextlib import contextmanager
from typing import Callable, NamedTuple

import click
import requests
from dotenv import find_dotenv, load_dotenv

from app.utils import BackendSession
from fncli.backend import FncliBackendAPI
from fncli.cmds.actions import open_pr_command, teardown_project_command
from fncli.cmds.common import (
    SECRET_CONFIGS,
    DagsterConfig,
    ProjectConfig,
    RepoConfig,
    ResultsRepoConfig,
    TriggerRepoConfig,
    build_backend_api,
    to_host_url,
)
from fncli.cmds.dataset import init_backend_dataset_command
from fncli.cmds.pr import merge_results_pr_command
from fncli.cmds.project import init_backend_project_command, project_healthcheck_command
from fncli.cmds.repository import (
    init_backend_results_repo_command,
    init_backend_trigger_repo_command,
    init_gitea_repo_command,
)
from fncli.cmds.secret import (
    init_dataset_secret_command,
    init_git_secret_command,
    verify_git_secret_command,
)
from fncli.cmds.state import get, project_resources, project_set_command, snapshot
from fncli.cmds.verify import Links, verify_project_command, verify_repo_command
from fncli.sensors import DagsterAPI


POLL_SECONDS = 1
SEPARATOR = "-" * 78


@contextmanager
def record_backend_calls(calls: list):
    """Note the method, path and status of every call the backend client makes while it is open."""
    original = BackendSession.request
    inherited = "request" not in vars(BackendSession)

    def request(self, method, url, *args, **kwargs):
        try:
            response = original(self, method, url, *args, **kwargs)
        except requests.HTTPError as error:
            calls.append((method.upper(), error.request.path_url, error.response.status_code))
            raise
        calls.append((method.upper(), response.request.path_url, response.status_code))
        return response

    BackendSession.request = request
    try:
        yield
    finally:
        if inherited:
            del BackendSession.request
        else:
            BackendSession.request = original


def show_backend_calls(calls: list):
    if not calls:
        return
    click.echo("nexus-api calls:")
    for (method, path, status), count in Counter(calls).items():
        click.echo(f"  {method} {path} -> {status}" + (f"  x {count}" if count > 1 else ""))


def as_json(name: str, value) -> str:
    """The object as JSON under the name of what it is, e.g. {"secret": {...}}."""
    return json.dumps({name: value}, indent=2)


def gitea_repo_url(config: RepoConfig, page: str = "") -> str:
    return to_host_url(f"{config.web_url}/{config.repo_path}{page}")


def show_repo(config_class):
    return lambda api, state: f"Open: {gitea_repo_url(config_class())}"


def show_secret(entity):
    """The secret as the backend returns it: label, key, namespace, enabled. Never its values."""
    return lambda api, state: as_json("secret", get(api, f"/global/secrets/{SECRET_CONFIGS[entity]().secret_label}"))


def show_project(api, state):
    return as_json("project", state["project"])


def show_resources(kind, name, config_class=None):
    """The project's resources of that kind, shown under the name of the global resource they are assigned, with the global repository, provider or dataset in each."""
    def show(api, state):
        resources = as_json(name, project_resources(api, state["project"]["id"])[kind])
        return f"Open: {gitea_repo_url(config_class())}\n{resources}" if config_class else resources

    return show


def result_lines(result: dict) -> list[str]:
    """A result's branch and pull request in Gitea, then the record."""
    lines = []
    if result["branch"]:
        config = ResultsRepoConfig()
        branch_page = "/tree/" if config.is_github else "/src/branch/"
        lines.append(f"Open: {gitea_repo_url(config, branch_page + result['branch'])}")
    if result["url"]:
        lines.append(f"Open: {to_host_url(result['url'])}")
    return [*lines, as_json("result", result)]


def show_pull_request(api, state):
    """The newest trigger pull request, its task and run, and the task's results: a link, then the record."""
    config = TriggerRepoConfig()
    links = Links(config.web_url, DagsterConfig().dagster_url, config.repo_path, config.pulls_page)
    project_id = state["project"]["id"]
    pull_requests = [pr for resource in state["trigger_resources"] for pr in resource["pull_requests"]]
    pr = max(pull_requests, key=lambda pr: pr["number"])
    lines = [f"Open: {links.trigger_pr(pr['number'])}", as_json("pull_request", pr)]
    if pr["task_id"]:
        task = get(api, f"/projects/{project_id}/tasks/{pr['task_id']}")
        run = DagsterAPI(links.dagster_url).get_task_run(task["id"])
        if run:
            lines.append(f"Open: {links.run(run['runId'])}")
        lines.append(as_json("task", task))
        for result in get(api, f"/projects/{project_id}/tasks/{task['id']}/results"):
            lines += result_lines(result)
    return "\n".join(lines)


def show_results_pr(api, state):
    result = get(api, f"/projects/{state['project']['id']}/results/{state['results'][0]['id']}")
    return "\n".join(result_lines(result))


class Wait(NamedTuple):
    # What the step waits for: "waiting for ..." and "timed out waiting for ..."
    description: str
    # True once the project's snapshot shows it
    done: Callable[[dict], bool]
    timeout: int = 30
    # snapshot fails while the project does not exist: only the step that creates it waits through that
    may_be_missing: bool = False


class Step(NamedTuple):
    title: str
    # What the step creates. {NAME} is filled from the environment when the step is shown.
    text: str
    # The fncli command line that does the same, for the user to see and reuse.
    line: str
    command: click.Command
    options: dict
    # After the step, poll the project's state until the change has arrived
    wait_for: Wait | None = None
    # What the step made, as text: "Open:" links first, then the backend objects as JSON. Called
    # with the backend API and the project's snapshot (None when the step has no wait_for).
    show: Callable[[FncliBackendAPI, dict | None], str] | None = None
    # Ask this (default No) before running it
    confirm: str | None = None


STEPS = [
    Step(
        "Create the Gitea repo the sensor will watch",
        "Gitea only. Creates {TEST_TRIGGER_REPO} under the Gitea admin user, or finds it.",
        "fncli init-gitea-repo --entity trigger",
        init_gitea_repo_command,
        {"entity": "trigger"},
        show=show_repo(TriggerRepoConfig),
    ),
    Step(
        "Create the Gitea repo the results go to",
        "Gitea only. Creates {TEST_RESULTS_REPO} the same way.",
        "fncli init-gitea-repo --entity results",
        init_gitea_repo_command,
        {"entity": "results"},
        show=show_repo(ResultsRepoConfig),
    ),
    Step(
        "Secret for the trigger repo's token (global)",
        "Mints a Gitea token (read:repository) and stores it as the global Secret "
        "{TEST_TRIGGER_REPO}-creds through the backend. The token lives only there; the "
        "repository record just names the secret.",
        "fncli init-git-secret --entity trigger",
        init_git_secret_command,
        {"entity": "trigger"},
        show=show_secret("trigger"),
    ),
    Step(
        "Secret for the results repo's token (global)",
        "Same, with a write:repository token, as {TEST_RESULTS_REPO}-creds.",
        "fncli init-git-secret --entity results",
        init_git_secret_command,
        {"entity": "results"},
        show=show_secret("results"),
    ),
    Step(
        "Secret for the dataset's credentials (global)",
        "Stores dummy database credentials as the global Secret "
        "{DEFAULT_PROJECT_DATASET}-dataset-creds.",
        "fncli init-dataset-secret",
        init_dataset_secret_command,
        {},
        show=show_secret("dataset"),
    ),
    Step(
        "Create the project",
        "Creates {TEST_PROJECT_NAME}. A new project is disabled: a results repository can only "
        "be assigned while it is disabled. Nothing is assigned to it yet.",
        "fncli init-backend-project",
        init_backend_project_command,
        {},
        wait_for=Wait("the project to exist", lambda state: True, may_be_missing=True),
        show=show_project,
    ),
    Step(
        "Trigger repository: the Git provider, the repository, and the project's resource",
        "Global: the GitProvider for the Gitea host, and the trigger repository on it (using "
        "the secret).\n"
        "Project: the resource, with watch_dir {TEST_TRIGGER_REPO_WATCH_DIR} and the "
        "branch to watch (the repo's default branch).",
        "fncli init-backend-trigger-repo",
        init_backend_trigger_repo_command,
        {},
        wait_for=Wait("the trigger repository resource", lambda state: bool(state["trigger_resources"])),
        show=show_resources("trigger", "trigger_repositories", TriggerRepoConfig),
    ),
    Step(
        "Results repository and the project's resource",
        "Global: the results repository, on the same provider.\n"
        "Project: the resource, with target_dir {TEST_RESULTS_TARGET_DIR}.",
        "fncli init-backend-results-repo",
        init_backend_results_repo_command,
        {},
        wait_for=Wait("the results repository resource", lambda state: bool(state["results_resources"])),
        show=show_resources("results", "results_repositories", ResultsRepoConfig),
    ),
    Step(
        "Dataset and the project's resource",
        "Global: the dataset {DEFAULT_PROJECT_DATASET} (a stand-in with dummy credentials).\n"
        "Project: the resource; the first dataset assigned becomes the project's default.",
        "fncli init-backend-dataset",
        init_backend_dataset_command,
        {},
        wait_for=Wait("the dataset resource", lambda state: bool(state["dataset_resources"])),
        show=show_resources("dataset", "datasets"),
    ),
    Step(
        "Check Gitea accepts the trigger token",
        "Read-only. Reads the stored token back from the cluster and calls Gitea with it, as "
        "the sensor will.",
        "fncli verify-git-secret --entity trigger",
        verify_git_secret_command,
        {"entity": "trigger"},
    ),
    Step(
        "Check Gitea accepts the results token",
        "Read-only, same for the results repo.",
        "fncli verify-git-secret --entity results",
        verify_git_secret_command,
        {"entity": "results"},
    ),
    Step(
        "Enable the project",
        "All resources are in place, so switch the project on.",
        "fncli project-set --enabled true",
        project_set_command,
        {"enabled": "true"},
        wait_for=Wait("the project to be enabled", lambda state: state["project"]["enabled"]),
        show=show_project,
    ),
    Step(
        "Project healthcheck",
        "Read-only. The backend reaches each repository with its stored token. Exits 1 unless "
        "the status is ok.",
        "fncli project-healthcheck",
        project_healthcheck_command,
        {},
    ),
    Step(
        "Open and merge a pull request in the trigger repo",
        "Gitea: a branch, a spec file under {TEST_TRIGGER_REPO_WATCH_DIR}, a PR, and the merge. "
        "Then watches the pull request become a task, the task run, and its results PR open "
        "(up to 5 minutes).",
        "fncli open-pr --kind watched --merge --watch --timeout 300",
        open_pr_command,
        {"kind": "watched", "merge": True, "watch": True, "timeout": 300},
        show=show_pull_request,
        wait_for=Wait("the results pull request to open", lambda state: bool(state["results"])),
    ),
    Step(
        "Merge the results pull request",
        "Gitea: merges the PR the task's results were delivered in. The sync sensor records it "
        "as MERGED within about a minute.",
        "fncli merge-results-pr --number \"$(fncli project-show | jq '.results[0].number')\"",
        merge_results_pr_command,
        # The number is the project's first results PR, looked up when the step runs
        {},
        # The results sync sensor records the merge on one of its ticks
        wait_for=Wait(
            "the results pull request to be recorded as MERGED",
            lambda state: state["results"][0]["step"] == "MERGED",
            timeout=180,
        ),
        show=show_results_pr,
    ),
    Step(
        "Check the project",
        "Read-only report: one line per check (ok, FAIL or SKIP).",
        "fncli verify-project",
        verify_project_command,
        {},
    ),
    Step(
        "Check every merged pull request ran",
        "Read-only. For each pull request: the task, the Dagster run, and the results delivery "
        "all agree.",
        "fncli verify-repo",
        verify_repo_command,
        {},
    ),
]

# Offered last, and not with --yes. Invoking the command bypasses its own confirmation, so
# the demo asks.
TEARDOWN_STEP = Step(
    "Tear the demo down (optional)",
    "Deletes the demo project, its global objects and secrets, and both Gitea repos. Only the "
    "demo's: the e2e project is untouched. It asks again, default No.",
    "fncli teardown-project",
    teardown_project_command,
    {},
    confirm="Delete the project, its secrets and both Gitea repos with all their pull requests?",
)


def wait_for_state(api: FncliBackendAPI, config: ProjectConfig, step: Step):
    """Poll the project every second until the step's change has arrived, printing what the step made when it changes."""
    wait = step.wait_for
    deadline = time.monotonic() + wait.timeout
    shown = None
    while True:
        try:
            state = snapshot(api, config.project_name)
        except click.ClickException:
            if not wait.may_be_missing:
                raise
            state = None
        text = step.show(api, state) if state else None
        changed = text is not None and text != shown
        if changed:
            shown = text
            click.echo(f"--- now:\n{text}")
        if state and wait.done(state):
            return
        if not changed:
            click.echo(f"waiting for {wait.description}...")
        if time.monotonic() >= deadline:
            raise click.ClickException(f"timed out waiting for {wait.description}")
        time.sleep(POLL_SECONDS)


def run_step(ctx: click.Context, config: ProjectConfig, step: Step):
    options = step.options
    if step.command is merge_results_pr_command:
        state = snapshot(build_backend_api(config), config.project_name)
        options = {"number": state["results"][0]["number"]}
    calls = []
    try:
        with record_backend_calls(calls):
            ctx.invoke(step.command, **options)
    except click.exceptions.Exit as done:
        # A step that watches its work (open-pr --watch) ends with Exit(0) when it went well:
        # only a failure stops the demo.
        if done.exit_code:
            raise
    finally:
        show_backend_calls(calls)
    if step.wait_for:
        wait_for_state(build_backend_api(config), config, step)
    elif step.show:
        click.echo(f"--- now:\n{step.show(build_backend_api(config), None)}")


@click.command("demo")
@click.option(
    "-y", "--yes", "yes_to_all", is_flag=True,
    help="Run every step without asking. The teardown is left out.",
)
@click.option(
    "--from", "from_step", type=click.IntRange(min=1), default=1, show_default=True,
    help="Start at this step.",
)
@click.option(
    "--env-file", default=".demo.env", show_default=True,
    help="The demo's names, found from the current directory up. .demo-github.env runs it on GitHub.",
)
@click.pass_context
def demo_command(ctx, yes_to_all, from_step, env_file):
    """
    Set up everything needed to watch a Gitea repo with fncli, then prove it works, one step
    at a time. Before each step it says what the step creates (a global object, a project
    resource, or Gitea only), shows the command and asks: Enter runs it, s skips it, q quits.

    Every step is idempotent, so the demo can be rerun. A failing step stops it: rerun with
    --from N. The names it uses are in .demo.env in the repo root (cp .demo.env.example
    .demo.env); the cluster addresses come from .dev.env. After each step it shows what the
    step made (links to open in the browser, and the backend objects as JSON). After a step
    that changes the project it waits for the change to show, polling every second.

    Needs the dev cluster with Tilt running and the Dagster sensors already running.
    """
    path = find_dotenv(env_file, usecwd=True)
    if not path:
        raise click.ClickException(
            f"{env_file} not found. From the repo root: cp {env_file}.example {env_file}"
        )
    # The group has loaded .dev.env without overriding what is set: the demo's names must win.
    load_dotenv(path, override=True)
    config = ProjectConfig()
    click.echo(
        "Demo project: {TEST_PROJECT_NAME}. Trigger repo: {TEST_TRIGGER_REPO}. "
        "Results repo: {TEST_RESULTS_REPO}.".format_map(os.environ)
    )
    steps = STEPS if yes_to_all else [*STEPS, TEARDOWN_STEP]
    for number, step in enumerate(steps, start=1):
        if number < from_step:
            continue
        click.echo(f"\n{SEPARATOR}")
        click.secho(f"Step {number}: {step.title}", bold=True)
        click.echo(step.text.format_map(os.environ))
        click.secho(f"$ {step.line}", fg="cyan")
        if not yes_to_all:
            answer = click.prompt("[Enter] run, [s]kip, [q]uit", default="", show_default=False)
            if answer.strip().lower() == "s":
                continue
            if answer.strip().lower() == "q":
                return
            if step.confirm and not click.confirm(step.confirm, default=False):
                continue
        run_step(ctx, config, step)
    click.echo("\nDone.")


COMMANDS = [demo_command]
