import re
from unittest.mock import MagicMock

import dagster as dg
import pytest

from app.definitions.sensors.base import IN_FLIGHT
from app.definitions.sensors.git.pr_ingest import PullRequestIngestSensor
from app.models import TriggerRepository
from app.tests.conftest import SAMPLE_TRIGGER_REPOSITORY


def repo(id=1, uri="github.com/org/repo", pr_cursor="2026-01-01T00:00:00Z"):
    return TriggerRepository(**{
        **SAMPLE_TRIGGER_REPOSITORY, "id": id, "uri": uri, "repo_path": "/".join(uri.split("/")[-2:]),
        "pr_cursor": pr_cursor,
    })


def git_pr(number):
    return {
        "number": number, "title": f"PR {number}", "user": {"login": "dev"}, "base": {"ref": "main"},
        "merged_at": "2026-06-26T10:00:00Z", "merge_commit_sha": f"sha{number}",
    }


def fake_git_api(merged_numbers):
    git_api = MagicMock()
    git_api.get_new_merged_pulls.return_value = [{"number": n} for n in merged_numbers]
    git_api.get_pull_request.side_effect = lambda repo_path, number: git_pr(number)
    git_api.get_pull_request_files.return_value = [{"filename": "spec.json", "status": "added"}]
    return git_api


def run(repos, git_apis_by_repo_id, in_flight=()):
    context = MagicMock()
    context.instance.get_runs.side_effect = lambda filters, limit: (
        [MagicMock()] if filters.tags["fn/repo_id"] in in_flight else []
    )
    backend_api = MagicMock()
    backend_api.get_pollable_trigger_repositories.return_value = repos
    git_apis = MagicMock()
    git_apis.for_repository.side_effect = lambda r: git_apis_by_repo_id[r.id]
    sensor = PullRequestIngestSensor(context=context, backend_api=backend_api, git_apis=git_apis)
    return list(sensor()), backend_api


def test_skips_when_there_are_no_repositories():
    results, _ = run([], {})

    assert len(results) == 1 and isinstance(results[0], dg.SkipReason)
    assert "No new pull requests" in results[0].skip_message


def test_only_polls_active_repositories_of_enabled_projects():
    _, backend_api = run([repo(1)], {1: fake_git_api([])})

    backend_api.get_pollable_trigger_repositories.assert_called_once_with()
    backend_api.get_projects.assert_not_called()


def test_the_sensor_only_checks_and_never_posts_or_fetches_pull_requests():
    git_api = fake_git_api([5, 6])

    _, backend_api = run([repo(1)], {1: git_api})

    backend_api.create_pull_requests_batch.assert_not_called()
    git_api.get_pull_request.assert_not_called()
    git_api.get_pull_request_files.assert_not_called()


def test_requests_one_run_per_repository_with_new_prs():
    apis = {1: fake_git_api([5, 6]), 2: fake_git_api([]), 3: fake_git_api([9])}

    results, _ = run([repo(1), repo(2, uri="github.com/org/none"), repo(3, uri="github.com/org/other")], apis)

    assert all(isinstance(r, dg.RunRequest) for r in results)
    assert [r.run_config["ops"]["ingest_pull_requests"]["config"] for r in results] == [{"repo_id": 1}, {"repo_id": 3}]


def test_the_run_is_tagged_as_an_ingest_and_not_a_task():
    results, _ = run([repo(1)], {1: fake_git_api([5])})

    assert results[0].tags == {"fn/trigger": "ingest", "fn/repo_id": "1"}


def test_the_run_key_is_the_cursor_and_the_retry_slot():
    results, _ = run([repo(1, pr_cursor="2026-03-03T03:03:03Z")], {1: fake_git_api([7, 12, 9])})

    assert re.fullmatch(r"ingest/1/2026-03-03T03:03:03Z/\d+", results[0].run_key)


def test_a_new_cursor_gives_a_new_run_key():
    old, _ = run([repo(1, pr_cursor="2026-03-03T03:03:03Z")], {1: fake_git_api([7])})
    new, _ = run([repo(1, pr_cursor="2026-04-04T04:04:04Z")], {1: fake_git_api([7])})

    assert old[0].run_key != new[0].run_key


def test_a_repository_with_an_ingest_run_in_flight_is_skipped_without_checking_the_provider():
    apis = {1: fake_git_api([5]), 2: fake_git_api([6])}

    results, _ = run([repo(1), repo(2, uri="github.com/org/other")], apis, in_flight={"1"})

    assert [r.run_config["ops"]["ingest_pull_requests"]["config"]["repo_id"] for r in results] == [2]
    apis[1].get_new_merged_pulls.assert_not_called()


def test_the_in_flight_check_filters_on_the_ingest_tags_and_statuses():
    repository = repo(7)
    context = MagicMock()
    context.instance.get_runs.return_value = []
    backend_api = MagicMock()
    backend_api.get_pollable_trigger_repositories.return_value = [repository]
    sensor = PullRequestIngestSensor(context=context, backend_api=backend_api, git_apis=MagicMock())

    list(sensor())

    filters = context.instance.get_runs.call_args.kwargs["filters"]
    assert filters.job_name == "ingest_pull_requests_job"
    assert filters.tags == {"fn/trigger": "ingest", "fn/repo_id": "7"}
    assert set(filters.statuses) == set(IN_FLIGHT)


def test_queries_the_provider_from_the_global_cursor_without_a_base_branch():
    git_api = fake_git_api([5])
    repository = repo(1, uri="https://gitea.fn.svc:3000/org/repo", pr_cursor="2026-03-03T03:03:03Z")

    run([repository], {1: git_api})

    git_api.get_new_merged_pulls.assert_called_once_with(repo_path="org/repo", merged_after="2026-03-03T03:03:03Z")


def test_skips_when_no_repository_has_new_prs():
    results, _ = run([repo(1)], {1: fake_git_api([])})

    assert len(results) == 1 and "No new pull requests" in results[0].skip_message


def failing_check_apis():
    broken = MagicMock()
    broken.get_new_merged_pulls.side_effect = RuntimeError("provider down")
    return broken


def test_a_failing_repository_does_not_stop_the_others():
    apis = {1: fake_git_api([5]), 2: failing_check_apis(), 3: fake_git_api([7])}

    results, _ = run([repo(1), repo(2, uri="github.com/org/bad"), repo(3, uri="github.com/org/other")], apis)

    assert [r.run_config["ops"]["ingest_pull_requests"]["config"]["repo_id"] for r in results] == [1, 3]


def test_the_tick_fails_naming_the_repositories_when_no_run_launched():
    apis = {1: failing_check_apis(), 2: fake_git_api([])}

    with pytest.raises(RuntimeError, match="Ingest failed for github.com/org/bad"):
        run([repo(1, uri="github.com/org/bad"), repo(2)], apis)
