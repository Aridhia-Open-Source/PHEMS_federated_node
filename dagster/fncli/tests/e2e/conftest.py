"""
Fixtures and helpers for the end-to-end tests. Run against a live dev cluster with `.dev.env` present:

    pytest dagster --e2e -v               # all of them: the happy path, the failure paths, the long failure paths
    pytest dagster --e2e success -v       # the happy path only
    pytest dagster --e2e failure -v       # the quick failure paths only
    pytest dagster --e2e failure_long -v  # the long-running failure paths only

The project is cleared at the start of each run and left in place afterwards for inspection; E2E_TEARDOWN=1 also tears it
down at the end. Nothing here runs at import time, so a normal test run
collects and skips these tests without a cluster.
"""

import json
import logging
import os
import time
from pathlib import Path

import click
import pytest
from dotenv import find_dotenv, load_dotenv

from fncli.backend import repo_path_of
from fncli.cli import cli
from fncli.cmds.common import DagsterConfig, GiteaConfig, ProjectConfig, build_backend_api, build_gitea_api
from fncli.cmds.pr import (
    commit_gitea_file_command,
    create_gitea_branch_command,
    create_gitea_pr_command,
    merge_gitea_pr_command,
    new_branch_name,
)
from fncli.cmds.project import project_healthcheck_command
from fncli.cmds.secret import verify_git_secret_command
from fncli.cmds.state import snapshot
from fncli.k8s import (
    ENV_CONFIGMAP,
    get_configmap_value,
    restart_code_server,
    set_configmap_value,
)
from fncli.nodefile.loader import load_context, load_node_file
from fncli.sensors import DagsterAPI

logger = logging.getLogger("e2e")

# Each state list runs in the order a state is reached; a poll can miss one in between.
PR_STATES = ["UNKNOWN", "YIELDED"]
TASK_STATUSES = ["PENDING", "QUEUED", "RUNNING", "SUCCESS"]
RESULT_STEPS = ["UNKNOWN", "PUSHED", "OPENED", "MERGED"]
# Values that never lead on to a later state: a wait for a later state fails at once instead of at the timeout
DEAD_ENDS = ["FAILED", "REVOKED", "STALE"]


def reached(order: list[str], value: str, minimum: str) -> bool:
    """Whether value is minimum or later in order. A value outside it (REJECTED, CLOSED) has not reached it; a dead end fails the test."""
    if value in DEAD_ENDS:
        pytest.fail(f"Found {value}, which will never reach {minimum}")
    return value in order and order.index(value) >= order.index(minimum)


# The dev project and its global resources, and the two extra projects on the same ones, as node files, on the node
# of the example context
BOOTSTRAP_EXAMPLES = Path(__file__).parents[4] / "bootstrap" / "examples"
CONTEXT_FILE = BOOTSTRAP_EXAMPLES / "context.yaml"
GLOBALS_FILE = BOOTSTRAP_EXAMPLES / "globals-e2e.yaml"
PROJECT_FILE = BOOTSTRAP_EXAMPLES / "projects" / "e2e.yaml"
SECOND_PROJECTS_FILE = BOOTSTRAP_EXAMPLES / "projects" / "e2e-second-projects.yaml"


def node_args(file: Path) -> list[str]:
    return ["-f", str(file), "--context", str(CONTEXT_FILE)]


def apply_node(fncli):
    """`fncli apply` of the dev project's node files: the secrets, provider, repositories, dataset and Gitea repositories, then the project."""
    fncli.run("apply", *node_args(GLOBALS_FILE), "-y")
    fncli.run("apply", *node_args(PROJECT_FILE), "-y")


def delete_node(fncli):
    """`fncli delete` of the dev project, then `--all` of its global resources."""
    fncli.run("delete", *node_args(PROJECT_FILE), "-y")
    fncli.run("delete", *node_args(GLOBALS_FILE), "--all", "-y")


def delete_gitea_leftovers(fncli):
    """What `fncli delete` leaves in Gitea: the repositories and the OAuth apps the node file names, so a run starts on fresh ones."""
    node = load_node_file(GLOBALS_FILE)
    gitea = build_gitea_api(GiteaConfig(GITEA_ADMIN_USER=load_context(CONTEXT_FILE).node.gitea_admin_user))
    for repository in node.repositories.triggers + node.repositories.results:
        gitea.delete_repo(repo_path_of(repository.uri).split("/")[1])
    for secret in node.secrets.values():
        if secret.gitea_oauth:
            gitea.delete_oauth_app(secret.gitea_oauth.app)


def verify_git_secret(entity: str):
    def verify(fncli):
        fncli.call(verify_git_secret_command, entity=entity)

    return verify


def project_healthcheck(fncli):
    fncli.call(project_healthcheck_command)


def trigger_secret_label() -> str:
    """The label of the secret the node file's trigger repository takes its git credentials from."""
    return load_node_file(GLOBALS_FILE).repositories.triggers[0].secret


def rotate_trigger_secret(fncli):
    """`fncli apply --rotate` of the trigger repository's secret: its OAuth app is authorised again and the new credentials stored."""
    fncli.run("apply", *node_args(GLOBALS_FILE), "--rotate", trigger_secret_label(), "-y")


def apply_second_project(fncli, name: str):
    fncli.run("apply", *node_args(SECOND_PROJECTS_FILE), "--project", name, "-y")


def delete_second_projects(fncli):
    """Every project of the second-projects node file that exists; its global resources are the dev project's and stay."""
    fncli.run("delete", *node_args(SECOND_PROJECTS_FILE), "-y")


# The steps that set up the dev project and that clear it, each run as one test: the id names the step
SETUP_STEPS = [
    pytest.param(apply_node, id="apply"),
    pytest.param(verify_git_secret("trigger"), id="verify-git-secret[trigger]"),
    pytest.param(verify_git_secret("results"), id="verify-git-secret[results]"),
    pytest.param(project_healthcheck, id="project-healthcheck"),
]
TEARDOWN_STEPS = [
    # First: the dev project's global resources are refused (409) while a second project still uses them
    pytest.param(delete_second_projects, id="delete-second-projects"),
    pytest.param(delete_node, id="delete"),
    pytest.param(delete_gitea_leftovers, id="delete-gitea-leftovers"),
]


def pull_requests(snapshot: dict) -> list[dict]:
    return [pr for resource in snapshot["trigger_resources"] for pr in resource["pull_requests"]]


def counts(snapshot: dict) -> tuple[int, int]:
    """(pull requests, tasks): what the "nothing happened" checks compare."""
    return len(pull_requests(snapshot)), len(snapshot["tasks"])


def stored_count(snapshot: dict) -> int:
    """Pull requests stored for the trigger repository, whether or not the project resource got a trigger for them."""
    return sum(resource["stored_pr_count"] for resource in snapshot["trigger_resources"])


def summary(snapshot: dict) -> dict:
    """The part of a snapshot a failure message shows."""
    return {
        "project": {k: snapshot["project"][k] for k in ("enabled", "revoked")},
        "resources": [{k: resource[k] for k in ("enabled", "revoked", "active", "global_enabled")} for resource in snapshot["trigger_resources"]],
        "prs": pull_requests(snapshot),
        "stored_prs": stored_count(snapshot),
        "tasks": snapshot["tasks"],
        "results": snapshot["results"],
    }


def teardown_step(fncli, step, final: bool = False):
    """One teardown step; the final teardown only runs with E2E_TEARDOWN=1."""
    if final and os.environ.get("E2E_TEARDOWN") != "1":
        pytest.skip("the project is kept for inspection: set E2E_TEARDOWN=1 to tear it down at the end")
    step(fncli)


INTERVAL_KEY = "DAGSTER_SENSORS_MIN_INTERVAL_SECONDS"
RETRY_INTERVAL_KEY = "DAGSTER_SENSORS_RETRY_INTERVAL_SECONDS"
APP_DEFAULT_INTERVAL = 30  # seconds: what the sensors use when the cluster's config does not set the interval


def tick_seconds() -> float:
    """The shortest interval of a sensor tick, as the cluster has it configured."""
    load_dotenv(find_dotenv(".dev.env", usecwd=True))
    value = get_configmap_value(ENV_CONFIGMAP, GiteaConfig().namespace, INTERVAL_KEY)
    return float(value) if value else APP_DEFAULT_INTERVAL


def set_sensor_interval(seconds: int, retry_seconds: int) -> tuple[str | None, str | None]:
    """Patch the sensor interval and the retry interval in the cluster's Dagster config and restart the code server so they take effect.

    Returns the previous values, to restore them with the same call. The restart stops the sensors (their initial status is
    STOPPED unless the chart says otherwise), so start them again afterwards.
    """
    load_dotenv(find_dotenv(".dev.env", usecwd=True))  # the autouse fast_sensors fixture runs before the fncli fixture loads it
    namespace = GiteaConfig().namespace
    previous = get_configmap_value(ENV_CONFIGMAP, namespace, INTERVAL_KEY)
    logger.info(f"Setting the sensor interval to {seconds}s (was {previous}) and restarting the code server")
    previous_retry = get_configmap_value(ENV_CONFIGMAP, namespace, RETRY_INTERVAL_KEY)
    set_configmap_value(ENV_CONFIGMAP, namespace, INTERVAL_KEY, str(seconds))
    set_configmap_value(ENV_CONFIGMAP, namespace, RETRY_INTERVAL_KEY, str(retry_seconds))
    restart_code_server(namespace)
    return previous, previous_retry


QUIET_SENSORS = ["git_pull_request_ingest_sensor", "git_pull_request_evaluate_sensor", "task_launcher_sensor"]


def tick_ids(api: DagsterAPI, sensor: str) -> set[str]:
    return {tick["id"] for tick in api.get_sensor_ticks(sensor)}


RETRY_INTERVAL = 5  # seconds: a failed run is retried at most this often
SENSOR_INTERVAL = 1  # seconds: the "nothing happens" checks then take a few of these


@pytest.fixture(scope="module", autouse=True)
def fast_sensors(request):
    """With E2E_FAST_SENSORS=1, run every e2e module with a 1 s sensor interval, and put the cluster's interval back afterwards,
    even when a test failed. Otherwise the cluster's interval and code server are left alone.

    The code server restarts both times, which stops the sensors. With E2E_FAST_SENSORS=1 start them again before the run
    (`fncli start-sensor --group all`); the restore leaves them stopped, as a fresh install does.
    """
    if os.environ.get("E2E_FAST_SENSORS") != "1":
        yield
        return
    previous, previous_retry = set_sensor_interval(SENSOR_INTERVAL, RETRY_INTERVAL)

    def restore():
        if previous is not None:
            set_sensor_interval(int(previous), int(previous_retry))

    request.addfinalizer(restore)
    yield


def quiet_wait(ticks: int = 3, sensors: list[str] = QUIET_SENSORS):
    """The wait of the "nothing happens" checks: until each sensor has run `ticks` new ticks, so "nothing happened" was
    seen across ticks that really ran (a stopped or stuck sensor fails here instead of passing the check)."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    before = {sensor: tick_ids(api, sensor) for sensor in sensors}
    logger.info(f"Waiting for {ticks} new ticks of {len(sensors)} sensors to see that nothing happens")

    def ticked():
        new = {sensor: len(tick_ids(api, sensor) - before[sensor]) for sensor in sensors}
        return all(count >= ticks for count in new.values()) or None

    # A tick can take several times the minimum interval when the daemon is busy
    interval = tick_seconds()
    wait_for(ticked, max(60, ticks * interval * 15), f"{ticks} new ticks of {sensors}", interval=max(1, interval))


@pytest.fixture(autouse=True)
def env():
    """Replaces the unit tests' fake settings: the e2e tests use the real .dev.env."""


POLL_SECONDS = 2  # how often a wait for something to happen looks at the project


def wait_for(predicate, timeout: float, describe: str, interval: float = POLL_SECONDS):
    """Poll predicate() until it returns something truthy, and return that. On timeout fail with `describe()`'s message."""
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result:
            logger.info(f"Done: {describe}")
            return result
        logger.info(f"Waiting for {describe}")
        if time.monotonic() >= deadline:
            pytest.fail(f"Timed out after {timeout}s waiting for {describe}")
        time.sleep(interval)


class Fncli:
    """The fncli commands and the project snapshot, against the live cluster."""

    def __init__(self):
        load_dotenv(find_dotenv(".dev.env", usecwd=True))
        self.config = ProjectConfig()
        self.backend_api = build_backend_api(self.config)

    def run(self, *args: str):
        """Run an fncli command as the CLI would, its output going straight to the terminal."""
        # Without standalone mode click returns a command's exit code (or its return value) instead of exiting
        code = cli.main(list(args), standalone_mode=False)
        assert not isinstance(code, int) or code == 0, f"fncli {' '.join(args)} exited {code}"

    def call(self, command, **options):
        """Run one command with its options, the unset ones at their defaults, and return what it returns. A non-zero exit fails the test."""
        with click.Context(command) as ctx:
            try:
                return ctx.invoke(command, **options)
            except click.exceptions.Exit as exit_:
                if exit_.exit_code:
                    pytest.fail(f"fncli {command.name} {options} exited {exit_.exit_code}")

    def exit_code(self, command, **options) -> int:
        """Run one command and return its exit code, for the tests that expect a failure."""
        with click.Context(command) as ctx:
            try:
                ctx.invoke(command, **options)
            except click.exceptions.Exit as exit_:
                return exit_.exit_code
        return 0

    def snapshot(self, project: str | None = None) -> dict:
        """The snapshot of the test project, or of another one by name."""
        return snapshot(self.backend_api, project or self.config.project_name)

    def wait_for_state(self, what: str, timeout: float, check, project: str | None = None, interval: float = POLL_SECONDS):
        """Poll the project snapshot until check(snapshot) is truthy and return that. On timeout the failure carries the last snapshot of PRs, tasks and results."""
        last = {}

        def poll():
            last["snapshot"] = self.snapshot(project)
            return check(last["snapshot"])

        try:
            return wait_for(poll, timeout, what, interval)
        except pytest.fail.Exception as failure:
            pytest.fail(f"{failure.msg}\nLast snapshot: {json.dumps(summary(last['snapshot']), indent=2)}")

    def assert_counts(self, expected: tuple[int, int], what: str):
        """Fail with the snapshot unless the (PRs, tasks) counts are still `expected`."""
        snap = self.snapshot()
        assert counts(snap) == expected, f"{what}: counts {counts(snap)} != {expected}\n{json.dumps(summary(snap), indent=2)}"


@pytest.fixture(scope="module")
def fncli():
    return Fncli()


# --- Shared by the failure-path suites (test_failure_paths.py and test_failure_paths_long.py) ---------------

QUIET_TICKS = 5
TASK_TIMEOUT = int(os.environ.get("E2E_TASK_TIMEOUT", 600))  # a task that fails to start can sit in a pull back-off
STEP_TIMEOUT = 300
# A task that has not finished, and a result that is still being delivered, are work in flight
UNFINISHED_TASK = ["PENDING", "QUEUED", "RUNNING"]
SECOND_PROJECT = "QaTwo"
# Every step a result can end at: a revoked result stays at REVOKED and is never delivered
SETTLED_STEPS = ["OPENED", "MERGED", "CLOSED", "REVOKED", "STALE"]
# The steps of a result that has been delivered
DELIVERED_STEPS = ["OPENED", "MERGED"]


def create_branch(fncli, flow, key):
    flow[f"{key}_branch"] = new_branch_name()
    fncli.call(create_gitea_branch_command, branch=flow[f"{key}_branch"])


def commit_file(fncli, flow, key, kind):
    fncli.call(commit_gitea_file_command, branch=flow[f"{key}_branch"], kind=kind)


def create_pr(fncli, flow, key, kind):
    flow[f"{key}_pr"] = fncli.call(create_gitea_pr_command, branch=flow[f"{key}_branch"], kind=kind)["number"]


def merge_pr(fncli, flow, key):
    fncli.call(merge_gitea_pr_command, number=flow[f"{key}_pr"], watch=False, timeout=0)


def pr_of(snapshot, flow, key):
    return next((pr for pr in pull_requests(snapshot) if pr["number"] == flow[f"{key}_pr"]), None)


def trigger_resource(snapshot):
    return snapshot["trigger_resources"][0]


def tasks_finished(snapshot):
    return all(task["status"] not in UNFINISHED_TASK for task in snapshot["tasks"])


def drained(snapshot):
    return tasks_finished(snapshot) and all(r["step"] in SETTLED_STEPS for r in snapshot["results"])


def record_counts(fncli, flow, key):
    flow[key] = counts(fncli.snapshot())
    logger.info(f"{key}: (PRs, tasks) = {flow[key]}")


def grew_by_one(flow, key):
    prs, tasks = flow[key]
    return lambda snapshot: counts(snapshot) == (prs + 1, tasks + 1)


def merge_watched_pr(fncli, flow, key):
    create_branch(fncli, flow, key)
    commit_file(fncli, flow, key, "watched")
    create_pr(fncli, flow, key, "watched")
    merge_pr(fncli, flow, key)


def assert_no_new_task(fncli, flow, key, what):
    """After a few sensor ticks the project still has the tasks it had when the counts were taken."""
    quiet_wait(QUIET_TICKS)
    snapshot = fncli.snapshot()
    assert len(snapshot["tasks"]) == flow[key][1], f"{what}: a task was created\n{json.dumps(summary(snapshot), indent=2)}"


def record_stored(fncli, flow, key):
    """Records the counts and, for the resource that gets no trigger, how many pull requests the repository has stored."""
    record_counts(fncli, flow, key)
    flow[f"{key}_stored"] = stored_count(fncli.snapshot())


def stored_without_a_trigger(flow, key):
    """The pull request is stored (+1, read from the repository: the resource gets no trigger for it) and has no task."""
    return lambda snapshot: stored_count(snapshot) == flow[f"{key}_stored"] + 1 and counts(snapshot) == flow[key]


def results_of(snapshot, task_id):
    return [r for r in snapshot["results"] if r["task_id"] == task_id]


def task_has_status(flow, key, status):
    """The task of the group once it has the status. Failing at once if it FAILED when something else was waited for."""

    def check(snapshot):
        task = next((t for t in snapshot["tasks"] if t["id"] == flow[key]), None)
        if task and task["status"] == "FAILED" and status != "FAILED":
            pytest.fail(f"task {flow[key]} FAILED while waiting for {status}: {task}")
        return task if task and task["status"] == status else None

    return check


def result_with(flow, key, step, state=None):
    """The task's result once it is at the step (and in the state, when given)."""
    return lambda snapshot: next(
        (r for r in results_of(snapshot, flow[key]) if r["step"] == step and (state is None or r["state"] == state)), None
    )


def yielded_with_task(flow, key):
    def check(snapshot):
        pr = pr_of(snapshot, flow, key)
        return pr if pr and pr["state"] == "YIELDED" and pr["task_id"] else None

    return check


def merge_pr_with_task(fncli, flow, key):
    """A watched PR merged, its task created: the task id goes to flow[f"{key}_task"]."""
    merge_watched_pr(fncli, flow, key)
    pr = fncli.wait_for_state(f"PR #{flow[f'{key}_pr']} YIELDED with a task_id", STEP_TIMEOUT, yielded_with_task(flow, key))
    flow[f"{key}_task"] = pr["task_id"]
