"""
Fixtures and helpers for the end-to-end tests. Run against a live dev cluster with `.dev.env` present:

    pytest dagster --e2e -v            # all of them
    pytest dagster --e2e success -v    # the happy path only
    pytest dagster --e2e failure -v    # the failure paths only

The project is cleared at the start of each run and left in place afterwards for inspection; E2E_TEARDOWN=1 also tears it
down at the end. Nothing here runs at import time, so a normal test run
collects and skips these tests without a cluster.
"""

import json
import logging
import os
import time

import click
import pytest
from dotenv import find_dotenv, load_dotenv

from fncli.cli import cli
from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.common import DagsterConfig, GiteaConfig, ProjectConfig, build_backend_api
from fncli.cmds.state import snapshot
from fncli.k8s import (
    ENV_CONFIGMAP,
    get_configmap_value,
    restart_code_server,
    set_configmap_value,
)
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


def step_id(step) -> str:
    """The test id of a (command, options) step: `init-gitea-repo[trigger]`, or just the name."""
    command, options = step
    return f"{command.name}[{','.join(map(str, options.values()))}]" if options else command.name


SETUP_IDS = [step_id(step) for step in SETUP_STEPS]
TEARDOWN_IDS = [step_id(step) for step in TEARDOWN_STEPS]


def pull_requests(snapshot: dict) -> list[dict]:
    return [pr for link in snapshot["trigger_links"] for pr in link["pull_requests"]]


def counts(snapshot: dict) -> tuple[int, int]:
    """(pull requests, tasks): what the "nothing happened" checks compare."""
    return len(pull_requests(snapshot)), len(snapshot["tasks"])


def summary(snapshot: dict) -> dict:
    """The part of a snapshot a failure message shows."""
    return {
        "project": {k: snapshot["project"][k] for k in ("enabled", "revoked")},
        "links": [{k: link[k] for k in ("enabled", "revoked", "active", "global_enabled")} for link in snapshot["trigger_links"]],
        "prs": pull_requests(snapshot),
        "tasks": snapshot["tasks"],
        "results": snapshot["results"],
    }


def start_sensor(sensor: str, timeout: float = 150):
    # start-sensor takes a group, not a name, so the API call it makes for each sensor is made here.
    # Poll until the sensor is available, since the location may still be loading after a code server restart.
    api = DagsterAPI(DagsterConfig().dagster_url)
    deadline = time.time() + timeout
    last_error = None

    while time.time() < deadline:
        try:
            return api.start_sensor(sensor)
        except RuntimeError as error:
            error_str = str(error)
            # Right after a code server restart the sensors are not loaded yet
            if "SensorNotFoundError" not in error_str:
                raise
            last_error = error_str
            logger.info(f"Sensor {sensor} not found yet, waiting for location to load")
            time.sleep(1)

    raise RuntimeError(f"Sensor {sensor} did not load within {timeout}s. Last error: {last_error}")


def teardown_step(fncli, command, options, final: bool = False):
    """One teardown step; the final teardown only runs with E2E_TEARDOWN=1."""
    if final and os.environ.get("E2E_TEARDOWN") != "1":
        pytest.skip("the project is kept for inspection: set E2E_TEARDOWN=1 to tear it down at the end")
    fncli.call(command, **options)


INTERVAL_KEY = "DAGSTER_SENSORS_MIN_INTERVAL_SECONDS"
RETRY_INTERVAL_KEY = "DAGSTER_SENSORS_RETRY_INTERVAL_SECONDS"
_tick_seconds = {"value": float(os.environ.get(INTERVAL_KEY, 30))}


def tick_seconds() -> float:
    """The shortest interval of a sensor tick, as the sensors are configured (or as a test set it)."""
    return _tick_seconds["value"]


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
    _tick_seconds["value"] = float(seconds)
    return previous, previous_retry


QUIET_SENSORS = ["git_pull_request_ingest_sensor", "git_pull_request_evaluate_sensor", "task_launcher_sensor"]


def tick_ids(api: DagsterAPI, sensor: str) -> set[str]:
    return {tick["id"] for tick in api.get_sensor_ticks(sensor)}


RETRY_INTERVAL = 5  # seconds: a failed run is retried at most this often
SENSOR_INTERVAL = 1  # seconds: the "nothing happens" checks then take a few of these


@pytest.fixture(scope="module", autouse=True)
def fast_sensors(request):
    """Run every e2e module with a 1 s sensor interval, and put the cluster's interval back afterwards, even when a test failed.

    Skipped when E2E_KEEP_INTERVAL=1. The code server restarts both times, which stops the sensors: each module's test_start_sensor
    starts them again after setup, and the restore leaves them stopped, as a fresh install does.
    """
    if os.environ.get("E2E_KEEP_INTERVAL") == "1":
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
    wait_for(ticked, max(60, ticks * tick_seconds() * 15), f"{ticks} new ticks of {sensors}", interval=max(1, tick_seconds()))


@pytest.fixture(autouse=True)
def env():
    """Replaces the unit tests' fake settings: the e2e tests use the real .dev.env."""


def wait_for(predicate, timeout: float, describe: str, interval: float = 10):
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

    def wait_for_state(self, what: str, timeout: float, check, project: str | None = None, interval: float = 10):
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
