from unittest.mock import MagicMock

import dagster as dg
import pytest

from app.definitions.sensors.git.pr_ingest import PullRequestIngestSensor
from app.models import ProjectTriggerRepository
from app.tests.conftest import SAMPLE_REPOSITORY_OBJ


def repo(id=1, uri="github.com/org/repo", pr_cursor="2026-01-01T00:00:00Z", base_branch="main", project_id=1):
    return ProjectTriggerRepository(
        **{**SAMPLE_REPOSITORY_OBJ, "id": id, "pr_cursor": pr_cursor, "base_branch": base_branch,
         "project_id": project_id,
         "trigger_repository": {**SAMPLE_REPOSITORY_OBJ["trigger_repository"], "id": id, "uri": uri}}
    )


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


def run(repos, git_apis_by_repo_id):
    backend_api = MagicMock()
    backend_api.get_project_trigger_repositories.return_value = repos
    git_apis = MagicMock()
    git_apis.for_repository.side_effect = lambda r: git_apis_by_repo_id[r.id]
    sensor = PullRequestIngestSensor(context=MagicMock(), backend_api=backend_api, git_apis=git_apis)
    return list(sensor()), backend_api


def test_skips_when_there_are_no_repositories():
    results, backend_api = run([], {})

    assert len(results) == 1 and isinstance(results[0], dg.SkipReason)
    assert "No repositories" in results[0].skip_message
    backend_api.create_pull_requests_batch.assert_not_called()


def test_two_assignments_of_one_repository_are_polled_once():
    git_api = fake_git_api([5])
    first, second = repo(1, project_id=1), repo(2, project_id=2)
    second.trigger_repository = first.trigger_repository

    results, backend_api = run([first, second], {1: git_api})

    git_api.get_new_merged_pulls.assert_called_once()
    backend_api.create_pull_requests_batch.assert_called_once()
    assert backend_api.create_pull_requests_batch.call_args.args[0] == 1
    assert "Saved 1 new pull requests" in results[0].skip_message


def test_only_polls_active_repositories_of_enabled_projects():
    _, backend_api = run([repo(1)], {1: fake_git_api([])})

    backend_api.get_project_trigger_repositories.assert_called_once_with(active_only=True, project_enabled=True)
    backend_api.get_projects.assert_not_called()


def test_posts_one_batch_per_repository_with_new_prs():
    apis = {1: fake_git_api([5, 6]), 2: fake_git_api([9])}

    results, backend_api = run([repo(1), repo(2, uri="github.com/org/other")], apis)

    assert backend_api.create_pull_requests_batch.call_count == 2
    first, second = backend_api.create_pull_requests_batch.call_args_list
    assert first.args[0] == 1 and [p["number"] for p in first.args[1]] == [5, 6]
    assert second.args[0] == 2 and [p["number"] for p in second.args[1]] == [9]
    assert "Saved 3 new pull requests" in results[0].skip_message


def test_the_batch_carries_the_facts_and_the_changed_paths():
    git_api = fake_git_api([5])

    _, backend_api = run([repo(1)], {1: git_api})

    body = backend_api.create_pull_requests_batch.call_args.args[1][0]
    assert body == {
        "number": 5, "title": "PR 5", "raised_by": "dev", "merged_at": "2026-06-26T10:00:00Z",
        "merge_commit_sha": "sha5", "base_branch": "main", "files_truncated": False,
        "changed_files": [{"path": "spec.json", "status": "added"}],
    }
    git_api.get_pull_request_files.assert_called_once_with("org/repo", 5)


def test_queries_the_provider_from_the_global_cursor_without_a_base_branch():
    git_api = fake_git_api([5])
    assignment = repo(1, uri="https://gitea.fn.svc:3000/org/repo", pr_cursor="2026-01-01T00:00:00Z", base_branch="dev")
    assignment.trigger_repository.pr_cursor = "2026-03-03T03:03:03Z"

    run([assignment], {1: git_api})

    git_api.get_new_merged_pulls.assert_called_once_with(repo_path="org/repo", merged_after="2026-03-03T03:03:03Z")
    git_api.get_pull_request.assert_called_once_with("org/repo", 5)


def test_a_repository_without_stored_prs_starts_at_the_earliest_assignment_cursor():
    git_api = fake_git_api([])
    first = repo(1, project_id=1, pr_cursor="2026-02-02T00:00:00Z")
    second = repo(2, project_id=2, pr_cursor="2026-01-01T00:00:00Z")
    second.trigger_repository = first.trigger_repository

    run([first, second], {1: git_api})

    git_api.get_new_merged_pulls.assert_called_once_with(repo_path="org/repo", merged_after="2026-01-01T00:00:00Z")


def test_a_repository_without_new_prs_posts_nothing():
    apis = {1: fake_git_api([]), 2: fake_git_api([9])}

    _, backend_api = run([repo(1), repo(2)], apis)

    backend_api.create_pull_requests_batch.assert_called_once()
    assert backend_api.create_pull_requests_batch.call_args.args[0] == 2


def test_skips_when_no_repository_has_new_prs():
    results, backend_api = run([repo(1)], {1: fake_git_api([])})

    assert "No new pull requests" in results[0].skip_message
    backend_api.create_pull_requests_batch.assert_not_called()


def test_a_failing_repository_aborts_the_tick_after_the_earlier_ones_were_saved():
    """The sensor fails fast: the error surfaces, and what was already posted stays posted."""
    broken = MagicMock()
    broken.get_new_merged_pulls.side_effect = RuntimeError("provider down")
    apis = {1: fake_git_api([5]), 2: broken, 3: fake_git_api([7])}

    backend_api = MagicMock()
    backend_api.get_project_trigger_repositories.return_value = [repo(1), repo(2), repo(3)]
    git_apis = MagicMock()
    git_apis.for_repository.side_effect = lambda r: apis[r.id]
    sensor = PullRequestIngestSensor(context=MagicMock(), backend_api=backend_api, git_apis=git_apis)

    with pytest.raises(RuntimeError, match="provider down"):
        list(sensor())

    assert [c.args[0] for c in backend_api.create_pull_requests_batch.call_args_list] == [1]
