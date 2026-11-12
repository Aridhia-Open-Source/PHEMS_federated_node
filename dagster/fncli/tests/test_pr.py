import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import click
from click.testing import CliRunner
import pytest
import requests

from fncli.cmds import pr
from fncli.cmds.pr import KINDS, PrConfig, file_for, new_branch_name
from app.models import TriggerState

@pytest.fixture
def config():
    return PrConfig(pr_image="busybox:1")


def spec_of(content):
    return json.loads(content)["spec"]


def test_the_kinds():
    assert KINDS == ["watched", "unwatched", "invalid", "failing"]


def test_watched_file_is_under_the_watch_dir_with_a_valid_spec(config):
    path, content = file_for(config, "pr-1", "watched")

    assert path == "specs/pr-1.json"
    assert json.loads(content) == {"spec": {"image": "busybox:1"}}


def test_watched_file_carries_the_extra_env_from_test_pr_env(monkeypatch):
    monkeypatch.setenv("TEST_PR_ENV", '{"EXAMPLE_FLAG": "1"}')
    _, content = file_for(PrConfig(pr_image="busybox:1"), "pr-1", "watched")

    assert spec_of(content)["env"] == {"EXAMPLE_FLAG": "1"}


def test_watched_file_carries_the_tags_from_test_pr_tags(monkeypatch):
    monkeypatch.setenv("TEST_PR_TAGS", '{"team": "a"}')
    _, content = file_for(PrConfig(pr_image="busybox:1"), "pr-1", "watched")

    assert spec_of(content)["tags"] == {"team": "a"}


def test_watched_file_carries_the_config_from_test_pr_config(monkeypatch):
    monkeypatch.setenv("TEST_PR_CONFIG", '{"threshold": 0.5, "labels": ["a"]}')
    _, content = file_for(PrConfig(pr_image="busybox:1"), "pr-1", "watched")

    assert spec_of(content)["config"] == {"threshold": 0.5, "labels": ["a"]}


def test_the_spec_file_has_none_of_the_removed_keys(monkeypatch):
    monkeypatch.setenv("TEST_PR_ENV", '{"A": "1"}')
    monkeypatch.setenv("TEST_PR_TAGS", '{"team": "a"}')
    monkeypatch.setenv("TEST_PR_CONFIG", '{"k": 1}')
    _, content = file_for(PrConfig(pr_image="busybox:1"), "pr-1", "watched")

    assert list(json.loads(content)) == ["spec"]
    assert list(spec_of(content)) == ["image", "env", "tags", "config"]


def test_invalid_file_is_watched_but_has_a_field_the_spec_forbids(config):
    path, content = file_for(config, "pr-1", "invalid")

    assert path.startswith("specs/") and path.endswith(".json")
    assert spec_of(content) == {"image": "busybox:1", "unknown_field": True}


def test_unwatched_file_is_outside_the_watch_dir(config):
    path, _ = file_for(config, "pr-1", "unwatched")

    assert not path.startswith(config.watch_dir)
    assert not path.endswith(".json")


def test_repo_path_is_the_admin_user_and_repo():
    assert PrConfig(gitea_admin_user="admin").repo_path == "admin/trigger"


def test_branch_names_are_prefixed_with_the_time_and_a_random_suffix():
    name = new_branch_name()

    prefix, stamp, suffix = name.split("-")
    assert prefix == "pr" and stamp.isdigit() and len(suffix) == 6


def test_branch_names_made_in_the_same_second_differ():
    assert new_branch_name() != new_branch_name()


# --watch

class FakeBackend:
    def __init__(self, prs, task_status="SUCCESS", deliveries=("OPENED",), sensors=None):
        self.prs = prs
        self.task_status = task_status
        self.deliveries = list(deliveries)
        self.sensors = sensors or {}

    def get_task_results(self, project_id, task_id):
        """
        Each delivery is None (no result yet), a step, or a (step, error) of a failed attempt: a failed
        push (step UNKNOWN, state FAILED) or a failed opening of the PR (step PUSHED, state DELIVERED).
        """
        delivery = self.deliveries.pop(0) if len(self.deliveries) > 1 else self.deliveries[0]
        if delivery is None:
            return []
        step, error = delivery if isinstance(delivery, tuple) else (delivery, None)
        opened = step in ("OPENED", "MERGED", "CLOSED")
        state = "DELIVERED" if step != "UNKNOWN" else "FAILED" if error else "IN_PROGRESS"
        return [SimpleNamespace(
            id=1, type="PR", task_id=task_id, results_repository_id=2, step=step, state=state, attempts=1,
            commit_sha="abc", error=error, number=3 if opened else None,
            url="http://gitea.fn.svc:4000/gitea_admin/results/pulls/3" if opened else None,
        )]

    def get_sensor_status(self, name):
        return self.sensors.get(name, "RUNNING")

    def find_repository(self, uri, project_id):
        return SimpleNamespace(trigger_repository=SimpleNamespace(id=7), repo_path="gitea_admin/trigger")

    def get_pull_requests(self, project_id, repo_id):
        assert (project_id, repo_id) == (1, 7)
        return self.prs.pop(0) if len(self.prs) > 1 else self.prs[0]

    def get_task(self, project_id, task_id):
        return SimpleNamespace(
            id=task_id, status=self.task_status, attempt=1, executor_run_id="abc",
            started_at="2026-01-01T10:00:00Z", completed_at="2026-01-01T10:01:00Z",
        )


def run_of(status):
    return {
        "runId": "abc", "status": status, "jobName": "k8s_pipes_job",
        "tags": [{"key": "fn/attempt", "value": "1"}],
    }


def pr_of(state, cause=None):
    return SimpleNamespace(project_id=1, number=5, state=TriggerState(state), state_cause=cause, task_id=9)


@pytest.fixture
def watch(monkeypatch):
    """Runs watch_pr against a fake backend and Dagster, returning the exit code."""

    def run(prs, runs=(None,), sensors=None, timeout=300, deliveries=("OPENED",)):
        runs = list(runs)
        dagster_api = MagicMock()
        def get_task_run(task_id):
            run = runs.pop(0) if len(runs) > 1 else runs[0]
            if isinstance(run, Exception):
                raise run
            return run

        dagster_api.get_task_run.side_effect = get_task_run
        dagster_api.get_sensor_state.side_effect = lambda name: {"status": (sensors or {}).get(name, "RUNNING")}
        monkeypatch.setattr(
            pr, "build_backend_api",
            lambda config: FakeBackend(list(prs), deliveries=deliveries, sensors=sensors),
        )
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
    lines = [r.message for r in caplog.records]
    assert lines == [
        "PR: waiting for ingest",
        "PR: UNKNOWN",
        "PR: YIELDED",
        "Task 9: SUCCESS",
        "Run abc: STARTED",
        "Dagster run: http://localhost:3000/runs/abc",
        "Run abc: SUCCESS",
        "Delivery: OPENED",
    ]


def test_watch_rejected_exits_one_and_shows_the_cause(watch, caplog):
    caplog.set_level(logging.INFO, logger="pr")

    assert watch([[pr_of("REJECTED", "bad spec")]]) == 1
    assert "PR: REJECTED (bad spec)" in caplog.text


@pytest.mark.parametrize("status, code", [("SUCCESS", 0), ("FAILURE", 1), ("CANCELED", 1)])
def test_watch_run_status_sets_the_exit_code(watch, status, code):
    assert watch([[pr_of("YIELDED")]], [run_of(status)]) == code


def test_watch_waits_for_the_delivery_and_prints_each_change(watch, caplog):
    caplog.set_level(logging.INFO, logger="pr")

    code = watch(
        [[pr_of("YIELDED")]], [run_of("SUCCESS")], deliveries=[None, "UNKNOWN", "PUSHED", "OPENED"]
    )

    assert code == 0
    lines = [r.message for r in caplog.records if "Delivery" in r.message]
    assert lines == [
        "Delivery: waiting for the delivery sensor", "Delivery: UNKNOWN", "Delivery: PUSHED", "Delivery: OPENED"
    ]


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
def test_watch_ends_on_a_results_pr_already_merged_or_closed(watch, caplog, state):
    caplog.set_level(logging.INFO, logger="pr")

    assert watch([[pr_of("YIELDED")]], [run_of("SUCCESS")], deliveries=[state]) == 0
    assert f"Delivery: {state}" in caplog.text


def test_watch_a_pushed_result_waits_for_the_results_pr_sensor_to_open_the_pr(watch, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="pr")
    monkeypatch.setattr(pr, "DELIVERY_SECONDS", 0.05)

    assert watch([[pr_of("YIELDED")]], [run_of("SUCCESS")], deliveries=["PUSHED"]) == 1
    assert "Delivery not finished after 0.05s, last seen: PUSHED" in caplog.text


def test_watch_a_result_is_delivered_once_pushed_when_the_results_pr_sensor_is_stopped(watch, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="pr")
    monkeypatch.setattr(pr, "DELIVERY_SECONDS", 5)

    assert watch(
        [[pr_of("YIELDED")]], [run_of("SUCCESS")], deliveries=[None, "UNKNOWN", "PUSHED"],
        sensors={"results_pull_request_sync_sensor": "STOPPED"},
    ) == 0
    assert "Delivery: PUSHED" in caplog.text
    assert "Delivery not finished" not in caplog.text


@pytest.mark.parametrize("step", ["UNKNOWN", "PUSHED"])
def test_watch_a_failed_delivery_stops_waiting_and_exits_one(watch, caplog, monkeypatch, step):
    """A failed push leaves the step UNKNOWN, a failed opening of the PR leaves it PUSHED."""
    caplog.set_level(logging.INFO, logger="pr")
    monkeypatch.setattr(pr, "DELIVERY_SECONDS", 5)

    assert watch([[pr_of("YIELDED")]], [run_of("SUCCESS")], deliveries=[(step, "zip too big")]) == 1
    assert f"Delivery: {step}: zip too big" in caplog.text
    assert "Delivery not finished" not in caplog.text


def test_watch_a_delivery_that_never_comes_is_bounded_and_fails_verification(
    watch, caplog, monkeypatch
):
    caplog.set_level(logging.INFO, logger="pr")
    monkeypatch.setattr(pr, "DELIVERY_SECONDS", 0.05)

    code = watch(
        [[pr_of("YIELDED")]], [run_of("SUCCESS")], deliveries=[None],
        sensors={"task_results_delivery_sensor": "STOPPED"},
    )

    assert code == 1
    assert "delivery stage: ['task_results_delivery_sensor']" in caplog.text


def test_watch_a_failed_run_does_not_wait_for_a_delivery(watch, caplog):
    caplog.set_level(logging.INFO, logger="pr")

    watch([[pr_of("YIELDED")]], [run_of("FAILURE")], deliveries=[None])

    assert "Delivery" not in caplog.text


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


def test_merge_results_pr_merges_in_the_results_repo(monkeypatch):
    merged = []

    class FakeGitea:
        def merge_pull_request(self, repo_path, number):
            merged.append((repo_path, number))

    monkeypatch.setattr(pr, "build_git_api", lambda config: FakeGitea())
    monkeypatch.setenv("TEST_RESULTS_REPO", "results-demo-repo")
    result = CliRunner().invoke(pr.merge_results_pr_command, ["--number", "3"])
    assert result.exit_code == 0
    assert merged == [("gitea_admin/results-demo-repo", 3)]


def test_a_failing_file_is_a_valid_spec_whose_task_exits_non_zero(config):
    path, content = file_for(config, "pr-1", "failing")

    spec = json.loads(content)["spec"]
    assert path.startswith(config.watch_dir)
    assert spec["env"] == {"PYPIPES_EXIT_CODE": "1"}
    assert "unknown_field" not in spec


@pytest.fixture
def researcher(monkeypatch):
    """The researcher's client, which the trigger repo's writes must use: never the node's (a token the backend mints)."""
    researcher = MagicMock()
    monkeypatch.setattr(pr, "build_researcher_git_api", lambda config: researcher)
    monkeypatch.setattr(pr, "build_git_api", lambda config: pytest.fail("the trigger repo's writes are the researcher's"))
    return researcher


def test_create_branch_is_the_researchers_off_the_base_branch_in_the_env(researcher, monkeypatch):
    monkeypatch.setenv("TEST_TRIGGER_REPO_BASE_BRANCH", "release")

    result = CliRunner().invoke(pr.create_gitea_branch_command, ["--branch", "b1"])

    assert result.exit_code == 0, result.output
    researcher.create_branch.assert_called_once_with("gitea_admin/trigger", "b1", "release")


def test_commit_file_is_the_researchers(researcher):
    result = CliRunner().invoke(pr.commit_gitea_file_command, ["--branch", "b1"])

    assert result.exit_code == 0, result.output
    assert researcher.create_file.call_args.args[:2] == ("gitea_admin/trigger", "specs/b1.json")


def test_create_pr_is_the_researchers_into_the_base_branch_in_the_env(researcher, monkeypatch):
    monkeypatch.setenv("TEST_TRIGGER_REPO_BASE_BRANCH", "release")
    researcher.create_pull_request.return_value = {"number": 4, "html_url": "http://gitea/pulls/4"}

    result = CliRunner().invoke(pr.create_gitea_pr_command, ["--branch", "b1"])

    assert result.exit_code == 0, result.output
    assert researcher.create_pull_request.call_args.kwargs["head_branch"] == "b1"
    assert researcher.create_pull_request.call_args.kwargs["base_branch"] == "release"


def test_without_the_env_var_the_pr_base_branch_is_the_one_the_projects_assignment_watches(monkeypatch):
    monkeypatch.delenv("TEST_TRIGGER_REPO_BASE_BRANCH", raising=False)
    backend_api = MagicMock()
    backend_api.find_repository.return_value = SimpleNamespace(base_branch="develop")
    monkeypatch.setattr(pr, "build_backend_api", lambda config: backend_api)

    assert pr.get_pr_base_branch(PrConfig()) == "develop"
    backend_api.find_repository.assert_called_once_with(
        "http://gitea.fn.svc:3000/gitea_admin/trigger", backend_api.find_project.return_value.id
    )


def test_merge_gitea_pr_is_the_researchers(researcher):
    result = CliRunner().invoke(pr.merge_gitea_pr_command, ["--number", "4"])

    assert result.exit_code == 0, result.output
    researcher.merge_pull_request.assert_called_once_with("gitea_admin/trigger", 4)
