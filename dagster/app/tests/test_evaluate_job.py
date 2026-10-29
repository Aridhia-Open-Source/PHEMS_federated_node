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
from app.models import PullRequestTrigger

WATCHED = "specs/a.json"
SPEC_FILE = json.dumps({"spec": {"docker_image": "a/b:1"}})


def pull_request(number=5, merged_at="2026-01-01T00:00:00Z", spec_files=(WATCHED,)):
    return PullRequestTrigger(
        project_id=4, trigger_repository_id=1, number=number, title="t", raised_by="dev",
        merged_at=merged_at, merge_commit_sha="abc", state="UNKNOWN",
        spec_files=list(spec_files),
    )


def http_error(status_code, text="bad"):
    return requests.HTTPError(response=MagicMock(status_code=status_code, text=text))


def run_evaluate(spec_files=(WATCHED,), contents=SPEC_FILE, backend_api=None):
    backend_api = backend_api or MagicMock()
    git_api = MagicMock()
    git_api.get_file_contents.return_value = contents
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    backend_api.get_project_trigger_repository.return_value = MagicMock(path="org/repo", watch_dir="specs/")
    context = dg.build_op_context(resources={"backend_api": backend_api, "git_apis": git_apis})
    evaluate_pull_request(context, pull_request(spec_files=spec_files))
    return backend_api


def test_a_ready_pr_sends_its_spec_file_and_patches_nothing():
    backend_api = run_evaluate()

    backend_api.get_project_trigger_repository.assert_called_once_with(4, 1)
    backend_api.create_task_for_pull_request.assert_called_once_with(4, 1, 5, SPEC_FILE)
    backend_api.patch_pull_request.assert_not_called()


def test_the_git_client_is_built_for_the_trigger_repository_and_the_project_of_the_pr():
    backend_api = MagicMock()
    git_api = MagicMock()
    git_api.get_file_contents.return_value = SPEC_FILE
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = dg.build_op_context(resources={"backend_api": backend_api, "git_apis": git_apis})

    evaluate_pull_request(context, pull_request())

    git_apis.for_repository.assert_called_once_with(
        backend_api.get_project_trigger_repository.return_value.trigger_repository, 4
    )


def test_a_pr_without_a_spec_file_is_patched_as_rejected():
    backend_api = run_evaluate(spec_files=[])

    backend_api.create_task_for_pull_request.assert_not_called()
    (project_id, repo_id, number, data), _ = backend_api.patch_pull_request.call_args
    assert (project_id, repo_id, number) == (4, 1, 5)
    assert data["state"] == "REJECTED" and "specs/" in data["state_cause"]


def test_a_pr_with_several_spec_files_is_patched_as_rejected():
    backend_api = run_evaluate(spec_files=[WATCHED, "specs/b.json"])

    backend_api.create_task_for_pull_request.assert_not_called()
    data = backend_api.patch_pull_request.call_args.args[3]
    assert data["state"] == "REJECTED" and data["state_cause"]


def test_a_400_from_the_task_endpoint_is_left_as_the_backend_rejected_it():
    backend_api = MagicMock()
    backend_api.create_task_for_pull_request.side_effect = http_error(400, "no such dataset")

    run_evaluate(backend_api=backend_api)

    backend_api.patch_pull_request.assert_not_called()


@pytest.mark.parametrize("cause", ["The project's trigger repository 1 is not active", "Project 'p' is disabled", "Project 1 is revoked"])
def test_a_409_from_the_task_endpoint_skips_the_pr(cause):
    """The PR stays UNKNOWN (no patch, no raise): it is evaluated again once the resource or project accepts a task."""
    backend_api = MagicMock()
    backend_api.create_task_for_pull_request.side_effect = http_error(409, cause)

    run_evaluate(backend_api=backend_api)

    backend_api.patch_pull_request.assert_not_called()


def test_a_backend_failure_raises_and_leaves_the_pr_untouched():
    backend_api = MagicMock()
    backend_api.create_task_for_pull_request.side_effect = http_error(503)

    with pytest.raises(requests.HTTPError):
        run_evaluate(backend_api=backend_api)

    backend_api.patch_pull_request.assert_not_called()


def test_a_git_failure_raises_and_leaves_the_pr_untouched():
    backend_api = MagicMock()
    git_api = MagicMock()
    git_api.get_file_contents.side_effect = ConnectionError("git down")
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
    context = dg.build_op_context(resources={"backend_api": backend_api}, op_config={"project_id": 4, "repo_id": 1})

    outputs = list(load_unknown_pull_requests(context))

    backend_api.get_pull_requests.assert_called_once_with(4, 1, state="UNKNOWN")
    assert [o.mapping_key for o in outputs] == ["5", "7"]


def test_the_job_maps_the_evaluation_over_the_load_and_caps_concurrency():
    assert {n.name for n in evaluate_repository_pull_requests_job.graph.nodes} == {
        "load_unknown_pull_requests", "evaluate_pull_request",
    }
    retry = evaluate_pull_request.retry_policy
    assert retry.max_retries == 3 and retry.backoff == dg.Backoff.EXPONENTIAL
    executor = evaluate_repository_pull_requests_job.executor_def
    assert executor.name == "multiprocess"
