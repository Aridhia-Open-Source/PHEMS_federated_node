from unittest.mock import MagicMock

import dagster as dg
import pytest

from app.definitions.sensors.git.ingest_job import MAX_BATCH_SIZE, ingest_pull_requests, ingest_pull_requests_job
from app.models import TriggerRepository
from app.tests.conftest import SAMPLE_TRIGGER_REPOSITORY


def repo(id=1, pr_cursor="2026-01-01T00:00:00Z"):
    return TriggerRepository(**{
        **SAMPLE_TRIGGER_REPOSITORY, "id": id, "uri": "github.com/org/repo", "repo_path": "org/repo", "pr_cursor": pr_cursor,
    })


def git_pr(number, merged_at="2026-06-26T10:00:00Z"):
    return {
        "number": number, "title": f"PR {number}", "user": {"login": "dev"}, "base": {"ref": "main"},
        "merged_at": merged_at, "merge_commit_sha": f"sha{number}",
    }


def fake_git_api(merged_numbers, files=({"filename": "spec.json", "status": "added"},)):
    git_api = MagicMock()
    git_api.get_new_merged_pulls.return_value = [{"number": n} for n in merged_numbers]
    git_api.get_pull_request.side_effect = lambda repo_path, number: git_pr(number)
    git_api.get_pull_request_files.return_value = list(files)
    return git_api


def run(git_api, repository=None, backend_api=None):
    backend_api = backend_api or MagicMock()
    backend_api.get_trigger_repository.return_value = repository or repo()
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = dg.build_op_context(
        op_config={"repo_id": 1}, resources={"backend_api": backend_api, "git_apis": git_apis}
    )
    ingest_pull_requests(context)
    return backend_api


def test_the_repository_is_read_again_for_a_fresh_cursor():
    git_api = fake_git_api([5])

    backend_api = run(git_api, repo(1, pr_cursor="2026-03-03T03:03:03Z"))

    backend_api.get_trigger_repository.assert_called_once_with(1)
    git_api.get_new_merged_pulls.assert_called_once_with(repo_path="org/repo", merged_after="2026-03-03T03:03:03Z")


def test_posts_the_new_prs_with_the_facts_and_the_changed_paths():
    git_api = fake_git_api([5])

    backend_api = run(git_api)

    backend_api.create_pull_requests_batch.assert_called_once()
    repo_id, body = backend_api.create_pull_requests_batch.call_args.args
    assert repo_id == 1 and body == [{
        "number": 5, "title": "PR 5", "raised_by": "dev", "merged_at": "2026-06-26T10:00:00Z",
        "merge_commit_sha": "sha5", "base_branch": "main", "files_truncated": False,
        "changed_files": [{"path": "spec.json", "status": "added"}],
    }]
    git_api.get_pull_request_files.assert_called_once_with("org/repo", 5)


def test_a_duplicate_changed_path_is_posted_once():
    files = [{"filename": "a.json", "status": "added"}, {"filename": "b.json", "status": "added"},
             {"filename": "a.json", "status": "added"}]

    backend_api = run(fake_git_api([5], files=files))

    paths = [f["path"] for f in backend_api.create_pull_requests_batch.call_args.args[1][0]["changed_files"]]
    assert paths == ["a.json", "b.json"]


def test_nothing_new_posts_nothing():
    backend_api = run(fake_git_api([]))

    backend_api.create_pull_requests_batch.assert_not_called()


def test_batches_are_at_most_100_pull_requests_oldest_first():
    numbers = list(range(1, 251))
    git_api = fake_git_api(reversed(numbers))
    git_api.get_pull_request.side_effect = lambda repo_path, number: git_pr(
        number, merged_at=f"2026-06-26T10:{number // 60:02d}:{number % 60:02d}Z"
    )

    backend_api = run(git_api)

    batches = [[p["number"] for p in c.args[1]] for c in backend_api.create_pull_requests_batch.call_args_list]
    assert MAX_BATCH_SIZE == 100
    assert [len(b) for b in batches] == [100, 100, 50]
    assert [n for b in batches for n in b] == numbers


def test_a_batch_the_backend_refuses_fails_the_run():
    backend_api = MagicMock()
    backend_api.create_pull_requests_batch.side_effect = RuntimeError("400")

    with pytest.raises(RuntimeError, match="400"):
        run(fake_git_api([5]), backend_api=backend_api)


def test_a_failing_provider_fails_the_run():
    git_api = MagicMock()
    git_api.get_new_merged_pulls.side_effect = RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        run(git_api)


def test_the_job_runs_the_ingest_op():
    assert [node.name for node in ingest_pull_requests_job.graph.nodes] == ["ingest_pull_requests"]
