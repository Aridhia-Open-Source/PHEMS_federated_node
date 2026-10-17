"""
Fixtures for the end-to-end happy path. Run against a live dev cluster with `.dev.env` present:

    pytest dagster/fncli/tests/e2e --e2e -v

E2E_KEEP=1 keeps the project afterwards. Nothing here runs at import time, so a normal test run
collects and skips these tests without a cluster.
"""

import json
import logging
import time

import click
import pytest
from dotenv import find_dotenv, load_dotenv

from fncli.cli import cli
from fncli.cmds.common import ProjectConfig, build_backend_api
from fncli.cmds.state import snapshot

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


def pull_requests(snapshot: dict) -> list[dict]:
    return [pr for link in snapshot["trigger_links"] for pr in link["pull_requests"]]


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
        """Run one command with its options, the unset ones at their defaults, and return what it returns."""
        with click.Context(command) as ctx:
            return ctx.invoke(command, **options)

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
            shown = {
                "prs": pull_requests(last["snapshot"]),
                "tasks": last["snapshot"]["tasks"],
                "results": last["snapshot"]["results"],
            }
            pytest.fail(f"{failure.msg}\nLast snapshot: {json.dumps(shown, indent=2)}")


@pytest.fixture(scope="module")
def fncli():
    return Fncli()
