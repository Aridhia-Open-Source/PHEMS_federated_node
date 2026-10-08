from types import SimpleNamespace

import pytest

from fncli.cmds.verify import Links, Report, verify_repo, verify_task
from fncli.dagster.models import TriggerState


class FakeBackend:
    def __init__(self, pr, task, results=None):
        self.pr = pr
        self.task = task
        self.results = [result_of()] if results is None else results

    def get_task_results(self, task_id):
        return self.results

    def get_pull_requests(self, repo_id):
        return [self.pr] if self.pr else []

    def get_task(self, task_id):
        return self.task


class FakeDagster:
    def __init__(self, run):
        self.run = run

    def get_task_run(self, task_id):
        return self.run


def result_of(**fields):
    result = dict(
        id=1, type="PR", task_id=9, status="DELIVERED", attempts=1, commit_sha="abc123", error=None,
        number=3, url="http://gitea.fn.svc:4000/gitea_admin/results/pulls/3",
        merge_status="OPEN",
    )
    return SimpleNamespace(**(result | fields))


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


LINKS = Links("http://localhost:4000", "http://localhost:3000", "gitea_admin/trigger")


def verify(pr=None, task=None, run=None, results=None):
    report = Report()
    verify_task(report, FakeBackend(pr, task, results), FakeDagster(run), LINKS, 7, 5)
    return report


def failures(report):
    return [name for status, name, _ in report.rows if status == "FAIL"]


def test_a_task_that_ran_and_matches_passes():
    report = verify(pr_of(), task_of(), run_of())

    assert report.failed == 0
    assert len(report.rows) == 18


def test_the_report_links_the_trigger_pr_the_run_and_the_results_pr():
    report = verify(pr_of(), task_of(), run_of())

    links = [(name, url) for status, name, url in report.rows if status == "link"]
    assert links == [
        ("Trigger PR", "http://localhost:4000/gitea_admin/trigger/pulls/5"),
        ("Dagster run", "http://localhost:3000/runs/abc"),
        ("Results PR", "http://localhost:4000/gitea_admin/results/pulls/3"),
    ]
    assert ("ok", "Delivery has a results PR", "#3, OPEN") in report.rows


def test_a_missing_pr_fails_and_stops():
    report = verify(pr=None)

    assert report.failed == 1
    assert len(report.rows) == 1


@pytest.mark.parametrize("state", ["UNKNOWN", "IGNORED", "REJECTED"])
def test_a_pr_that_was_not_yielded_fails_and_stops(state):
    report = verify(pr_of(state))

    assert failures(report) == ["PR was YIELDED, so it has a task"]
    assert len(report.rows) == 3


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


@pytest.mark.parametrize("results, failed", [
    ([result_of(status="FAILED", error="zip too big")], ["Results were DELIVERED"]),
    ([result_of(status="PENDING", commit_sha=None, number=None, url=None)],
     ["Results were DELIVERED", "Delivery has a commit_sha", "Delivery has a results PR"]),
    ([result_of(commit_sha=None)], ["Delivery has a commit_sha"]),
    ([result_of(number=None)], ["Delivery has a results PR"]),
    ([result_of(url=None)], ["Delivery has a results PR"]),
    ([], ["Task 9 has one results delivery: GET /tasks/9/results"]),
    ([result_of(), result_of(id=2)], ["Task 9 has one results delivery: GET /tasks/9/results"]),
])
def test_each_delivery_problem_is_reported(results, failed):
    report = verify(pr_of(), task_of(), run_of(), results)

    assert failures(report) == failed


def test_a_failed_delivery_shows_its_error():
    report = verify(pr_of(), task_of(), run_of(), [result_of(status="FAILED", error="zip too big")])

    assert ("FAIL", "Results were DELIVERED", "FAILED: zip too big") in report.rows


def test_a_failed_run_matching_its_task_still_fails_the_run_check():
    report = verify(pr_of(), task_of(status="FAILED"), run_of(status="FAILURE"))

    assert failures(report) == ["Run succeeded"]


def test_a_queued_run_needs_no_start_or_end_time():
    report = verify(
        pr_of(), task_of(status="QUEUED", started_at=None, completed_at=None), run_of(status="QUEUED")
    )

    assert failures(report) == ["Run succeeded"]


class RepoBackend:
    def __init__(self, prs, task=None):
        self.prs = prs
        self.task = task or task_of()

    def get_task_results(self, task_id):
        return [result_of()]

    def get_pull_requests(self, repo_id):
        return self.prs

    def get_task(self, task_id):
        return self.task


def numbered(number, state="YIELDED", cause=None):
    return SimpleNamespace(
        number=number, title=f"PR {number}", state=TriggerState(state), state_cause=cause, task_id=9
    )


def verify_all(prs, run=None, tail=None):
    return verify_repo(RepoBackend(prs), FakeDagster(run or run_of()), LINKS, 7, tail)


def test_repo_with_every_pr_fine_has_no_failures(capsys):
    prs = [numbered(1), numbered(2, "IGNORED", "no spec"), numbered(3, "REJECTED", "bad spec")]

    assert verify_all(prs) == 0
    out = capsys.readouterr().out
    assert "3 PRs checked, 0 checks failed" in out
    assert "PR was IGNORED, so no task is expected" in out


def test_repo_counts_the_failures_across_prs(capsys):
    prs = [numbered(1), numbered(2)]

    assert verify_all(prs, run_of(status="FAILURE")) == 4  # status mismatch + run not succeeded, twice
    assert "2 PRs checked, 4 checks failed" in capsys.readouterr().out


def test_repo_fails_a_pr_still_unknown(capsys):
    assert verify_all([numbered(1, "UNKNOWN")]) == 1
    assert "still UNKNOWN" in capsys.readouterr().out


def test_repo_tail_checks_only_the_last_prs_by_number(capsys):
    prs = [numbered(3), numbered(1), numbered(2)]

    verify_all(prs, tail=2)

    out = capsys.readouterr().out
    assert "PR #1" not in out and "PR #2" in out and "PR #3" in out
    assert "2 PRs checked" in out


def test_repo_with_no_prs_fails(capsys):
    assert verify_all([]) == 1
    assert "No pull requests in the repo" in capsys.readouterr().out
