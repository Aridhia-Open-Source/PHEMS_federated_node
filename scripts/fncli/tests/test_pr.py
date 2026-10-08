import importlib.util
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import click
import pytest
import requests
from pydantic import ValidationError

from fncli.cmds import pr
from fncli.cmds.pr import KINDS, PrConfig, file_for, new_branch_name
from fncli.dagster.models import TriggerState

SPEC_MODULE = Path(__file__).parents[2] / "../dagster/app/models/pull_request_spec.py"


@pytest.fixture(scope="module")
def spec_model():
    """The Dagster code location's own model, loaded by path: the two must agree."""
    spec = importlib.util.spec_from_file_location("pull_request_spec", SPEC_MODULE.resolve())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PullRequestSpec


@pytest.fixture
def config():
    return PrConfig(pr_image="busybox:1")


def spec_of(content):
    return json.loads(content)["spec"]


def test_the_kinds():
    assert KINDS == ["watched", "unwatched", "invalid"]


def test_watched_file_is_under_the_watch_dir_and_validates(config, spec_model):
    path, content = file_for(config, "pr-1", "watched")

    assert path == "specs/pr-1.json"
    spec = spec_model.model_validate(spec_of(content))
    assert spec.image == "busybox:1" and spec.name == "pr-1"


def test_invalid_file_is_watched_but_fails_the_spec(config, spec_model):
    path, content = file_for(config, "pr-1", "invalid")

    assert path.startswith("specs/") and path.endswith(".json")
    with pytest.raises(ValidationError):
        spec_model.model_validate(spec_of(content))


def test_unwatched_file_is_outside_the_watch_dir(config):
    path, _ = file_for(config, "pr-1", "unwatched")

    assert not path.startswith(config.watch_dir)
    assert not path.endswith(".json")


def test_repo_path_is_the_admin_user_and_repo():
    assert PrConfig(gitea_admin_user="admin").repo_path == "admin/trigger"


def test_branch_names_are_prefixed_with_the_time():
    name = new_branch_name()

    assert name.startswith("pr-") and name[3:].isdigit()


# --watch

class FakeBackend:
    def __init__(self, prs, task_status="SUCCESS"):
        self.prs = prs
        self.task_status = task_status

    def find_repository(self, uri, project_id):
        return SimpleNamespace(id=7)

    def get_pull_requests(self, repo_id):
        assert repo_id == 7
        return self.prs.pop(0) if len(self.prs) > 1 else self.prs[0]

    def get_task(self, task_id):
        return SimpleNamespace(
            id=task_id, status=self.task_status, attempt=1, dagster_run_id="abc",
            started_at="2026-01-01T10:00:00Z", completed_at="2026-01-01T10:01:00Z",
        )


def run_of(status):
    return {
        "runId": "abc", "status": status, "jobName": "k8s_pipes_job",
        "tags": [{"key": "attempt", "value": "1"}],
    }


def pr_of(state, cause=None):
    return SimpleNamespace(number=5, state=TriggerState(state), state_cause=cause, task_id=9)


@pytest.fixture
def watch(monkeypatch):
    """Runs watch_pr against a fake backend and Dagster, returning the exit code."""

    def run(prs, runs=(None,), sensors=None, timeout=300):
        runs = list(runs)
        dagster_api = MagicMock()
        def get_task_run(task_id):
            run = runs.pop(0) if len(runs) > 1 else runs[0]
            if isinstance(run, Exception):
                raise run
            return run

        dagster_api.get_task_run.side_effect = get_task_run
        dagster_api.get_sensor_state.side_effect = lambda name: {"status": (sensors or {}).get(name, "RUNNING")}
        monkeypatch.setattr(pr, "build_backend_api", lambda config: FakeBackend(list(prs)))
        monkeypatch.setattr(pr, "DagsterAPI", lambda url: dagster_api)
        monkeypatch.setattr(pr, "find_project", lambda config, api: SimpleNamespace(id=1))
        monkeypatch.setattr(pr, "POLL_SECONDS", 0)
        try:
            pr.watch_pr(PrConfig(), 5, timeout)
        except click.exceptions.Exit as exit:
            return exit.exit_code
        return 0

    return run


def test_watch_prints_each_change_once(watch, caplog):
    caplog.set_level(logging.INFO, logger="pr")
    runs = [run_of("STARTED"), run_of("SUCCESS")]

    code = watch([[], [pr_of("UNKNOWN")], [pr_of("YIELDED")]], runs)

    assert code == 0
    lines = [r.message.split(" ", 1)[1] for r in caplog.records]
    assert lines == [
        "PR: waiting for ingest",
        "PR: UNKNOWN",
        "PR: YIELDED",
        "Task 9: SUCCESS",
        "Run abc: STARTED",
        "Run abc: SUCCESS",
    ]


def test_watch_ignored_exits_zero(watch):
    assert watch([[pr_of("IGNORED", "no spec")]]) == 0


def test_watch_rejected_exits_one_and_shows_the_cause(watch, caplog):
    caplog.set_level(logging.INFO, logger="pr")

    assert watch([[pr_of("REJECTED", "bad spec")]]) == 1
    assert "PR: REJECTED (bad spec)" in caplog.text


@pytest.mark.parametrize("status, code", [("SUCCESS", 0), ("FAILURE", 1), ("CANCELED", 1)])
def test_watch_run_status_sets_the_exit_code(watch, status, code):
    assert watch([[pr_of("YIELDED")]], [run_of(status)]) == code


def test_watch_timeout_names_the_stopped_sensor_of_the_stage(watch, caplog):
    caplog.set_level(logging.INFO, logger="pr")

    code = watch([[pr_of("YIELDED")]], sensors={"task_launcher_sensor": "STOPPED"}, timeout=0.05)

    assert code == 1
    assert "launcher stage: ['task_launcher_sensor']" in caplog.text


def test_watch_survives_a_dropped_connection(watch, caplog):
    caplog.set_level(logging.INFO, logger="pr")
    outcomes = [requests.exceptions.ConnectionError("Remote end closed connection"), run_of("SUCCESS")]

    code = watch([[pr_of("YIELDED")]], runs=outcomes)

    assert code == 0
    assert caplog.text.count("connection error, retrying: Remote end closed connection") == 1
    assert "Run abc: SUCCESS" in caplog.text


def test_watch_gives_up_after_too_many_connection_errors(watch, caplog):
    caplog.set_level(logging.INFO, logger="pr")

    code = watch([[pr_of("YIELDED")]], runs=[requests.exceptions.ConnectionError("down")])

    assert code == 1
    assert f"{pr.MAX_CONNECTION_ERRORS} connection errors in a row" in caplog.text
