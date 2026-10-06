from types import SimpleNamespace

import pytest

from fncli.cmds.verify import Report, verify_task
from fncli.dagster.models import TriggerState


class FakeBackend:
    def __init__(self, pr, task):
        self.pr = pr
        self.task = task

    def get_pull_requests(self, repo_id):
        return [self.pr] if self.pr else []

    def get_task(self, task_id):
        return self.task


class FakeDagster:
    def __init__(self, run):
        self.run = run

    def get_task_run(self, task_id):
        return self.run


def pr_of(state="YIELDED"):
    return SimpleNamespace(number=5, state=TriggerState(state), state_cause=None, task_id=9)


def task_of(**fields):
    task = dict(
        id=9, status="SUCCESS", attempt=1, dagster_run_id="abc",
        started_at="2026-01-01T10:00:00Z", completed_at="2026-01-01T10:01:00Z",
    )
    return SimpleNamespace(**(task | fields))


def run_of(**fields):
    run = {
        "runId": "abc", "status": "SUCCESS", "jobName": "k8s_pipes_job",
        "tags": [{"key": "attempt", "value": "1"}],
    }
    return run | fields


def verify(pr=None, task=None, run=None):
    report = Report()
    verify_task(report, FakeBackend(pr, task), FakeDagster(run), 7, 5)
    return report


def failures(report):
    return [name for status, name, _ in report.rows if status == "FAIL"]


def test_a_task_that_ran_and_matches_passes():
    report = verify(pr_of(), task_of(), run_of())

    assert report.failed == 0
    assert len(report.rows) == 10


def test_a_missing_pr_fails_and_stops():
    report = verify(pr=None)

    assert report.failed == 1
    assert len(report.rows) == 1


@pytest.mark.parametrize("state", ["UNKNOWN", "IGNORED", "REJECTED"])
def test_a_pr_that_was_not_yielded_fails_and_stops(state):
    report = verify(pr_of(state))

    assert failures(report) == ["PR was YIELDED, so it has a task"]
    assert len(report.rows) == 2


def test_a_task_without_a_run_fails():
    report = verify(pr_of(), task_of(), run=None)

    assert failures(report) == ["Task 9 has a Dagster run: runs tagged task_id=9"]


@pytest.mark.parametrize("task_fields, run_fields, failed", [
    ({"status": "RUNNING"}, {}, "Task status matches the run"),
    ({"dagster_run_id": "other"}, {}, "Task holds the run's id"),
    ({"attempt": 2}, {}, "Task attempt matches the run's attempt tag"),
    ({"started_at": None}, {}, "Task has started_at"),
    ({"completed_at": None}, {}, "Task has completed_at"),
    ({}, {"jobName": "other_job"}, "Run is a k8s_pipes_job"),
])
def test_each_mismatch_is_reported(task_fields, run_fields, failed):
    report = verify(pr_of(), task_of(**task_fields), run_of(**run_fields))

    assert failures(report) == [failed]


def test_a_failed_run_matching_its_task_still_fails_the_run_check():
    report = verify(pr_of(), task_of(status="FAILED"), run_of(status="FAILURE"))

    assert failures(report) == ["Run succeeded"]


def test_a_queued_run_needs_no_start_or_end_time():
    report = verify(
        pr_of(), task_of(status="QUEUED", started_at=None, completed_at=None), run_of(status="QUEUED")
    )

    assert failures(report) == ["Run succeeded"]
