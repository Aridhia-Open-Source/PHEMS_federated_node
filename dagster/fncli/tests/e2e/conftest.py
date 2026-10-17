"""
Fixtures for the end-to-end happy path. Run against a live dev cluster with `.dev.env` present:

    pytest dagster/fncli/tests/e2e --e2e -v

E2E_KEEP=1 keeps the project afterwards. Nothing here runs at import time, so a normal test run
collects and skips these tests without a cluster.
"""

import os
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from dotenv import find_dotenv, load_dotenv

from fncli.cli import cli
from fncli.cmds.common import ProjectConfig, build_backend_api
from fncli.cmds.state import snapshot

# fncli reads .dev.env and its config from the current folder, which is the repo root
REPO_ROOT = Path(__file__).resolve().parents[4]


def wait_for(predicate, timeout: float, describe: str, interval: float = 10):
    """Poll predicate() until it returns something truthy, and return that. On timeout fail with `describe()`'s message."""
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result:
            return result
        if time.monotonic() >= deadline:
            pytest.fail(f"Timed out after {timeout}s waiting for {describe}")
        time.sleep(interval)


class Fncli:
    """The fncli commands and the project snapshot, against the live cluster."""

    def __init__(self):
        load_dotenv(find_dotenv(".dev.env", usecwd=True))
        self.runner = CliRunner()
        self.config = ProjectConfig()
        self.backend_api = build_backend_api(self.config)

    def run(self, *args: str):
        result = self.runner.invoke(cli, list(args))
        assert result.exit_code == 0, f"fncli {' '.join(args)} exited {result.exit_code}:\n{result.output}"
        return result

    def call(self, command, **options):
        """Run one command's function and return what it returns, which a CliRunner run drops."""
        return command.callback(**options)

    def snapshot(self) -> dict:
        return snapshot(self.backend_api, self.config.project_name)


@pytest.fixture(scope="module")
def fncli():
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    fn = Fncli()
    fn.run("teardown-project", "-y")
    fn.run("setup-project")
    fn.run("verify-project")
    yield fn
    if os.environ.get("E2E_KEEP") != "1":
        fn.run("teardown-project", "-y")
    os.chdir(cwd)
