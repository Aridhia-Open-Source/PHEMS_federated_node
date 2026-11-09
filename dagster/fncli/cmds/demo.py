"""
`fncli demo` walks the pull request process on a node that `fncli apply -f FILE` has already set up
(bootstrap/examples/demo-*.yaml), one confirmed step at a time, then proves it works. It creates and deletes nothing
itself: it first builds the plan `fncli diff` shows and stops unless the node already matches the file. The dataset
the project is assigned is not in the file: it is already on the node, made by `fncli experiment setup demo`. The
steps (checks, pull request, task, results) are the step commands, run in this process. They read the demo's names
from the env, which the demo sets from the file.
"""

import json
import os
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple

import click
import requests

from app.utils import BackendSession
from fncli.backend import FncliBackendAPI, repo_path_of
from fncli.cmds.actions import open_pr_command
from fncli.cmds.common import DagsterConfig, RepoConfig, ResultsRepoConfig, TriggerRepoConfig, to_host_url
from fncli.cmds.nodefile import node_file_option, open_node, quiet_backend_logs, render_change
from fncli.cmds.pr import merge_results_pr_command
from fncli.cmds.project import project_healthcheck_command
from fncli.cmds.secret import verify_git_secret_command
from fncli.cmds.state import get, snapshot
from fncli.cmds.verify import Links, verify_project_command, verify_repo_command
from fncli.nodefile import lookup
from fncli.nodefile.diff import ENSURE, UNCHANGED, BackendState, diff
from fncli.nodefile.loader import limit_to_project
from fncli.nodefile.schema import NodeFile, ProjectSpec
from fncli.nodefile.state import read_state
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


@dataclass
class Demo:
    """What the steps work on: the node file's one project, with the global resources it references"""

    node_file: Path
    node: NodeFile
    api: FncliBackendAPI
    project: ProjectSpec

    def read_state(self) -> BackendState:
        with quiet_backend_logs():
            return read_state(self.api)


def repository_uri(node: NodeFile, uri: str) -> str:
    """A repository's uri with its scheme, from its provider: the file keeps them without, and the env configs need it"""
    return f"{node.provider_for(uri).uri}/{repo_path_of(uri)}"


def step_env(node: NodeFile, project: ProjectSpec) -> dict[str, str]:
    """
    What the step commands (pull requests, checks, project-set) read from the env instead of from a node file: the
    project and its first trigger and results repositories and first dataset, and the node's addresses. GITEA_API_URI
    is never empty: those configs insist on it, and a GitHub-only file has no Gitea to give it.
    """
    trigger = project.repositories.triggers[0]
    results = project.repositories.results
    gitea = next((p for p in node.providers if p.type == "gitea"), node.provider_for(trigger.repository))
    return {
        "NEXUS_API_URL": node.node.url,
        "KEYCLOAK_NAMESPACE": node.node.keycloak_namespace,
        "GITEA_ADMIN_USER": node.node.gitea_admin_user,
        "GITEA_API_URI": gitea.api_uri,
        "TEST_PROJECT_NAME": project.name,
        "TEST_TRIGGER_REPO": repo_path_of(trigger.repository).split("/")[1],
        "TEST_TRIGGER_REPO_URI": repository_uri(node, trigger.repository),
        "TEST_TRIGGER_REPO_WATCH_DIR": trigger.watch_dir,
        "TEST_TRIGGER_REPO_BASE_BRANCH": trigger.base_branch,
        "TEST_RESULTS_REPO": repo_path_of(results.repository).split("/")[1],
        "TEST_RESULTS_REPO_URI": repository_uri(node, results.repository),
        "TEST_RESULTS_TARGET_DIR": results.target_dir,
        "TEST_RESULTS_REPO_BASE_BRANCH": results.base_branch,
        "DEFAULT_PROJECT_DATASET": project.datasets[0],
    }


def step_names(demo: Demo) -> dict[str, str]:
    """What a step's text and command line are filled from"""
    project = demo.project
    return {
        "file": str(demo.node_file),
        "project": project.name,
        "trigger_repo": repo_path_of(project.repositories.triggers[0].repository),
        "watch_dir": project.repositories.triggers[0].watch_dir,
        "results_repo": repo_path_of(project.repositories.results.repository),
        "target_dir": project.repositories.results.target_dir,
        "dataset": project.datasets[0],
    }


def gitea_repo_url(config: RepoConfig, page: str = "") -> str:
    return to_host_url(f"{config.web_url}/{config.repo_path}{page}")


def show_dataset(demo, state):
    dataset = lookup.present(demo.api.find_dataset(demo.project.datasets[0]), f"dataset {demo.project.datasets[0]}")
    return as_json("dataset", dataset.model_dump(mode="json"))


def result_lines(result: dict) -> list[str]:
    """A result's branch and pull request in the git host, then the record."""
    lines = []
    if result["branch"]:
        config = ResultsRepoConfig()
        branch_page = "/tree/" if config.is_github else "/src/branch/"
        lines.append(f"Open: {gitea_repo_url(config, branch_page + result['branch'])}")
    if result["url"]:
        lines.append(f"Open: {to_host_url(result['url'])}")
    return [*lines, as_json("result", result)]


def show_pull_request(demo, state):
    """The newest trigger pull request, its task and run, and the task's results: a link, then the record."""
    api = demo.api
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


def show_results_pr(demo, state):
    result = get(demo.api, f"/projects/{state['project']['id']}/results/{state['results'][0]['id']}")
    return "\n".join(result_lines(result))


class Wait(NamedTuple):
    # What the step waits for: "waiting for ..." and "timed out waiting for ..."
    description: str
    # True once the project's snapshot shows it
    done: Callable[[dict], bool]
    timeout: int = 30


class Step(NamedTuple):
    title: str
    # What the step does. {project}, {trigger_repo}, ... are filled from the node file when the step is shown.
    text: str
    # The fncli command line that does the same, for the user to see and reuse. Filled like the text.
    line: str
    # Does the step, in this process
    run: Callable[[click.Context, Demo], None]
    # After the step, poll the project's state until the change has arrived
    wait_for: Wait | None = None
    # What the step made, as text: "Open:" links first, then the backend objects as JSON. Called
    # with the demo and the project's snapshot (None when the step has no wait_for).
    show: Callable[[Demo, dict | None], str] | None = None


def command_step(command: click.Command, **options) -> Callable[[click.Context, Demo], None]:
    """A step that is one of the step commands, which read their names from the env"""
    return lambda ctx, demo: ctx.invoke(command, **options)


def check_dataset(ctx, demo):
    """The backend's dataset healthcheck: can the node log in to the database with the dataset's secret"""
    name = demo.project.datasets[0]
    health = demo.api.get_dataset_healthcheck(lookup.dataset_id(demo.api, name))
    check = health["health_check"]
    detail = f"{check['message']}, {check['latency_ms']} ms"
    if health["status"] != "ok":
        click.echo(f"[FAIL] dataset {name} at {health['host']}:{health['port']}: {health['status']} ({detail})")
        raise click.ClickException(
            "The node cannot connect to the dataset's database. For the demo database: fncli experiment up, "
            "fncli experiment seed demo, then fncli experiment setup demo"
        )
    click.echo(f"[  ok] dataset {name} at {health['host']}:{health['port']}: the node can log in ({detail})")


def require_applied(demo: Demo):
    """
    Stop unless the node already matches the file, by the plan `fncli diff` prints. A Gitea repository to ensure is
    not a difference: apply makes it in Gitea, never in the backend, and the plan lists it every time.
    """
    pending = [change for change in diff(demo.node, demo.read_state()) if change.action not in (UNCHANGED, ENSURE)]
    if pending:
        rows = "\n".join(line for change in pending for line in render_change(change, {}))
        raise click.ClickException(
            f"The node does not match {demo.node_file} yet:\n{rows}\nRun `fncli apply -f {demo.node_file}` first."
        )


def merge_results_pr(ctx, demo):
    """The project's first results pull request, looked up when the step runs"""
    ctx.invoke(merge_results_pr_command, number=snapshot(demo.api, demo.project.name)["results"][0]["number"])


STEPS = [
    Step(
        "Check the node can log in to the dataset's database",
        "Read-only. Global: the dataset {dataset} is already on the node (`fncli experiment setup demo` made it, "
        "with its database address and its secret). The backend connects to the database with the dataset's "
        "secret, as a task will. Stops the demo unless it can.",
        "GET /global/datasets/ID/healthcheck   # nexus-api",
        check_dataset,
        show=show_dataset,
    ),
    Step(
        "Check the git host accepts the trigger token",
        "Read-only. Asks the backend for a token for the trigger repo and calls the git host with it, as the "
        "sensor will.",
        "fncli verify-git-secret --entity trigger",
        command_step(verify_git_secret_command, entity="trigger"),
    ),
    Step(
        "Check the git host accepts the results token",
        "Read-only, same for the results repo.",
        "fncli verify-git-secret --entity results",
        command_step(verify_git_secret_command, entity="results"),
    ),
    Step(
        "Project healthcheck",
        "Read-only. The backend reaches each repository with its stored token. Exits 1 unless "
        "the status is ok.",
        "fncli project-healthcheck",
        command_step(project_healthcheck_command),
    ),
    Step(
        "Open and merge a pull request in the trigger repo",
        "A branch, a spec file under {watch_dir}, a PR, and the merge. Then watches the pull request become a "
        "task, the task run, and its results PR open (up to 5 minutes).",
        "fncli open-pr --kind watched --merge --watch --timeout 300",
        command_step(open_pr_command, kind="watched", merge=True, watch=True, timeout=300),
        show=show_pull_request,
        wait_for=Wait("the results pull request to open", lambda state: bool(state["results"])),
    ),
    Step(
        "Merge the results pull request",
        "Merges the PR the task's results were delivered in. The sync sensor records it "
        "as MERGED within about a minute.",
        "fncli merge-results-pr --number \"$(fncli project-show | jq '.results[0].number')\"",
        merge_results_pr,
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
        command_step(verify_project_command),
    ),
    Step(
        "Check every merged pull request ran",
        "Read-only. For each pull request: the task, the Dagster run, and the results delivery "
        "all agree.",
        "fncli verify-repo",
        command_step(verify_repo_command),
    ),
]


def wait_for_state(demo: Demo, step: Step):
    """Poll the project every second until the step's change has arrived, printing what the step made when it changes."""
    wait = step.wait_for
    deadline = time.monotonic() + wait.timeout
    shown = None
    while True:
        state = snapshot(demo.api, demo.project.name)
        text = step.show(demo, state)
        changed = text != shown
        if changed:
            shown = text
            click.echo(f"--- now:\n{text}")
        if wait.done(state):
            return
        if not changed:
            click.echo(f"waiting for {wait.description}...")
        if time.monotonic() >= deadline:
            raise click.ClickException(f"timed out waiting for {wait.description}")
        time.sleep(POLL_SECONDS)


def run_step(ctx: click.Context, demo: Demo, step: Step):
    calls = []
    try:
        with record_backend_calls(calls):
            step.run(ctx, demo)
    except click.exceptions.Exit as done:
        # A step that watches its work (open-pr --watch) ends with Exit(0) when it went well:
        # only a failure stops the demo.
        if done.exit_code:
            raise
    finally:
        show_backend_calls(calls)
    if step.wait_for:
        wait_for_state(demo, step)
    elif step.show:
        click.echo(f"--- now:\n{step.show(demo, None)}")


@click.command("demo")
@node_file_option
@click.option("--project", default=None, help="The project to demo, when the node file has more than one.")
@click.option("-y", "--yes", "yes_to_all", is_flag=True, help="Run every step without asking.")
@click.option(
    "--from", "from_step", type=click.IntRange(min=1), default=1, show_default=True,
    help="Start at this step.",
)
@click.pass_context
def demo_command(ctx, node_file, project, yes_to_all, from_step):
    """
    Walk the pull request process of a node file's project, one step at a time: checks that the node can reach the
    dataset's database and the git host, then a pull request into the trigger repository that is merged, becomes a
    task and delivers its results in a results pull request, which is merged, then checks of the whole project. It
    creates and deletes nothing: set the node up first with `fncli apply -f FILE`, and remove it afterwards with
    `fncli delete -f FILE [--all]`. It stops unless `fncli diff -f FILE` shows nothing to change.

    Before each step it says what the step does, shows the command and asks: Enter runs it, s skips it, q quits.
    A failing step stops it: rerun with --from N. The names it uses are the node file's: its one project, with that
    project's first trigger repository, results repository and dataset (bootstrap/examples/demo-gitea.yaml or
    demo-github.yaml). The dataset is not in the file: it must be on the node already (fncli experiment up, seed
    demo and setup demo). After each step it shows what the step made (links to open in the browser, and the backend
    objects as JSON). After a step that changes the project it waits for the change to show, polling every second.

    Needs the dev cluster with Tilt running and the Dagster sensors already running.
    """
    node, api = open_node(node_file, project)
    if project is None and len(node.projects) != 1:
        names = ", ".join(p.name for p in node.projects)
        raise click.ClickException(f"{node_file} has {len(node.projects)} projects: pick one with --project ({names})")
    node = limit_to_project(node, project or node.projects[0].name)
    spec = node.projects[0]
    if not spec.repositories.triggers or not spec.datasets:
        raise click.ClickException(f"Project {spec.name} needs a trigger repository and a dataset to demo")
    absent = [name for name in spec.datasets if api.find_dataset(name) is None]
    if absent:
        raise click.ClickException(
            f"Dataset {', '.join(absent)} is not on the node. Make it first: fncli experiment up, make experiments "
            "seed demo, fncli experiment setup demo"
        )
    demo = Demo(node_file, node, api, spec)
    require_applied(demo)
    # After open_node: it has loaded the node's env file over the env, and the demo's names must win over that
    os.environ.update(step_env(node, spec))
    names = step_names(demo)
    click.echo(
        "Demo project: {project}. Trigger repo: {trigger_repo}. Results repo: {results_repo}. "
        "Dataset: {dataset}.".format_map(names)
    )
    for number, step in enumerate(STEPS, start=1):
        if number < from_step:
            continue
        click.echo(f"\n{SEPARATOR}")
        click.secho(f"Step {number}: {step.title}", bold=True)
        click.echo(step.text.format_map(names))
        click.secho(f"$ {step.line.format_map(names)}", fg="cyan")
        if not yes_to_all:
            answer = click.prompt("[Enter] run, [s]kip, [q]uit", default="", show_default=False)
            if answer.strip().lower() == "s":
                continue
            if answer.strip().lower() == "q":
                return
        run_step(ctx, demo, step)
    click.echo("\nDone.")


COMMANDS = [demo_command]
