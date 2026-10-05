import json
from unittest.mock import MagicMock

import dagster as dg
import pytest
import requests

from app.definitions.sensors.git.evaluate_job import (
    evaluate_pull_request,
    evaluate_repository_pull_requests_job,
    load_unknown_pull_requests,
)
from app.models import PullRequest

WATCHED = {"filename": "specs/a.json", "status": "added"}
SPEC_FILE = json.dumps({"spec": {"docker_image": "a/b:1"}})


def pull_request(number=5, merged_at="2026-01-01T00:00:00Z"):
    return PullRequest(
        trigger_repository_id=1, number=number, title="t", raised_by="dev",
        merged_at=merged_at, merge_commit_sha="abc", state="UNKNOWN", payload={},
    )


def http_error(status_code, text="bad"):
    return requests.HTTPError(response=MagicMock(status_code=status_code, text=text))


def run_evaluate(files=(WATCHED,), contents=SPEC_FILE, backend_api=None):
    backend_api = backend_api or MagicMock()
    git_api = MagicMock()
    git_api.get_pull_request_files.return_value = list(files)
    git_api.get_file_contents.return_value = contents
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    backend_api.get_repository.return_value = MagicMock(path="org/repo", watch_dir="specs/")
    context = dg.build_op_context(resources={"backend_api": backend_api, "git_apis": git_apis})
    evaluate_pull_request(context, pull_request())
    return backend_api


def test_a_ready_pr_creates_its_task_and_patches_nothing():
    backend_api = run_evaluate()

    backend_api.create_task_for_pull_request.assert_called_once()
    args = backend_api.create_task_for_pull_request.call_args.args
    assert args[:2] == (1, 5) and args[2]["image"] == "a/b:1"
    backend_api.patch_pull_request.assert_not_called()


def test_an_ignored_pr_is_patched_with_its_reason():
    backend_api = run_evaluate(files=[])

    backend_api.create_task_for_pull_request.assert_not_called()
    (repo_id, number, data), _ = backend_api.patch_pull_request.call_args
    assert (repo_id, number) == (1, 5)
    assert data["state"] == "IGNORED" and "specs/" in data["state_cause"]


def test_a_rejected_pr_is_patched_with_its_reason():
    backend_api = run_evaluate(contents="not json")

    backend_api.create_task_for_pull_request.assert_not_called()
    data = backend_api.patch_pull_request.call_args.args[2]
    assert data["state"] == "REJECTED" and data["state_cause"]


def test_a_400_from_the_task_endpoint_rejects_with_its_message():
    backend_api = MagicMock()
    backend_api.create_task_for_pull_request.side_effect = http_error(400, "no such dataset")

    run_evaluate(backend_api=backend_api)

    backend_api.patch_pull_request.assert_called_once_with(
        1, 5, {"state": "REJECTED", "state_cause": "no such dataset"}
    )


def test_a_backend_failure_raises_and_leaves_the_pr_untouched():
    backend_api = MagicMock()
    backend_api.create_task_for_pull_request.side_effect = http_error(503)

    with pytest.raises(requests.HTTPError):
        run_evaluate(backend_api=backend_api)

    backend_api.patch_pull_request.assert_not_called()


def test_a_git_failure_raises_and_leaves_the_pr_untouched():
    backend_api = MagicMock()
    git_api = MagicMock()
    git_api.get_pull_request_files.side_effect = ConnectionError("git down")
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = dg.build_op_context(resources={"backend_api": backend_api, "git_apis": git_apis})

    with pytest.raises(ConnectionError):
        evaluate_pull_request(context, pull_request())

    backend_api.create_task_for_pull_request.assert_not_called()
    backend_api.patch_pull_request.assert_not_called()


def test_the_load_op_emits_the_unknown_prs_oldest_first():
    backend_api = MagicMock()
    backend_api.get_pull_requests.return_value = [
        pull_request(7, "2026-03-01T00:00:00Z"), pull_request(5, "2026-01-01T00:00:00Z"),
    ]
    context = dg.build_op_context(resources={"backend_api": backend_api}, op_config={"repo_id": 1})

    outputs = list(load_unknown_pull_requests(context))

    backend_api.get_pull_requests.assert_called_once_with(1, "UNKNOWN")
    assert [o.mapping_key for o in outputs] == ["5", "7"]


def test_the_job_maps_the_evaluation_over_the_load_and_caps_concurrency():
    assert {n.name for n in evaluate_repository_pull_requests_job.graph.nodes} == {
        "load_unknown_pull_requests", "evaluate_pull_request",
    }
    retry = evaluate_pull_request.retry_policy
    assert retry.max_retries == 3 and retry.backoff == dg.Backoff.EXPONENTIAL
    executor = evaluate_repository_pull_requests_job.executor_def
    assert executor.name == "multiprocess"
