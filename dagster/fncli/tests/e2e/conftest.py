"""
Fixtures and helpers for the end-to-end tests. Run against a live dev cluster with `.dev.env` present:

    pytest dagster --e2e -v            # all of them
    pytest dagster --e2e success -v    # the happy path only
    pytest dagster --e2e failure -v    # the failure paths only

E2E_KEEP=1 keeps the project afterwards. Nothing here runs at import time, so a normal test run
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
from fncli.cmds.common import DagsterConfig, ProjectConfig, build_backend_api
from fncli.cmds.state import snapshot
from fncli.k8s import ENV_CONFIGMAP, get_configmap_value, restart_code_server, set_configmap_value
from fncli.sensors import DagsterAPI

logger = logging.getLogger("e2e")

# Each state list runs in the order a state is reached; a poll can miss one in between.
PR_STATES = ["UNKNOWN", "YIELDED"]
TASK_STATUSES = ["PENDING", "QUEUED", "RUNNING", "SUCCESS"]
RESULT_STEPS = ["UNKNOWN", "PUSHED", "OPENED", "MERGED"]


def reached(order: list[str], value: str, minimum: str) -> bool:
    """Whether value is minimum or later in order. A value outside it (FAILED, REJECTED, CLOSED) has not reached it."""
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
        "links": [{k: link[k] for k in ("enabled", "revoked", "active", "global_enabled")} for link in snapshot["trigger_links"]],
        "prs": pull_requests(snapshot),
        "tasks": snapshot["tasks"],
        "results": snapshot["results"],
    }


def start_sensor(sensor: str):
    # start-sensor takes a group, not a name, so the API call it makes for each sensor is made here
    DagsterAPI(DagsterConfig().dagster_url).start_sensor(sensor)


def teardown_step(fncli, command, options, keep: bool = False):
    """One teardown step; with keep=True it is skipped when E2E_KEEP=1 (the final teardown)."""
    if keep and os.environ.get("E2E_KEEP") == "1":
        pytest.skip("E2E_KEEP=1 keeps the project")
    fncli.call(command, **options)


INTERVAL_KEY = "DAGSTER_SENSORS_MIN_INTERVAL_SECONDS"
_tick_seconds = {"value": float(os.environ.get(INTERVAL_KEY, 10))}


def tick_seconds() -> float:
    """The shortest interval of a sensor tick, as the sensors are configured (or as a test set it)."""
    return _tick_seconds["value"]


def set_sensor_interval(seconds: int) -> str | None:
    """Patch the sensor interval in the cluster's Dagster config and restart the code server so it takes effect.

    Returns the previous value, to restore it with the same call. The restart stops the sensors (their initial status is
    STOPPED unless the chart says otherwise), so start them again afterwards.
    """
    namespace = ProjectConfig().namespace
    previous = get_configmap_value(ENV_CONFIGMAP, namespace, INTERVAL_KEY)
    logger.info(f"Setting the sensor interval to {seconds}s (was {previous}) and restarting the code server")
    set_configmap_value(ENV_CONFIGMAP, namespace, INTERVAL_KEY, str(seconds))
    restart_code_server(namespace)
    _tick_seconds["value"] = float(seconds)
    return previous


def quiet_wait(ticks: int = 3):
    """The fixed wait of the "nothing happens" checks: a few sensor ticks, long enough for a sensor to have acted."""
    seconds = ticks * tick_seconds()
    logger.info(f"Waiting {seconds:.0f}s ({ticks} sensor ticks) to see that nothing happens")
    time.sleep(seconds)


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

    def snapshot(self) -> dict:
        return snapshot(self.backend_api, self.config.project_name)


    def wait_for_state(self, what: str, timeout: float, check):
        """Poll the project snapshot until check(snapshot) is truthy and return that. On timeout the failure carries the last snapshot of PRs, tasks and results."""
        last = {}

        def poll():
            last["snapshot"] = self.snapshot()
            return check(last["snapshot"])

        try:
            return wait_for(poll, timeout, what)
        except pytest.fail.Exception as failure:
            pytest.fail(f"{failure.msg}\nLast snapshot: {json.dumps(summary(last['snapshot']), indent=2)}")

    def assert_counts(self, expected: tuple[int, int], what: str):
        """Fail with the snapshot unless the (PRs, tasks) counts are still `expected`."""
        snap = self.snapshot()
        assert counts(snap) == expected, f"{what}: counts {counts(snap)} != {expected}\n{json.dumps(summary(snap), indent=2)}"


@pytest.fixture(scope="module")
def fncli():
    return Fncli()
