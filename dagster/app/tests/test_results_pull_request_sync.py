import re
from unittest.mock import MagicMock

import pytest
import requests

import dagster as dg

from app.definitions.sensors.git.pr_evaluate import IN_FLIGHT
from app.definitions.sensors.task import JOBS, SENSORS
from app.definitions.sensors.task.pull_request_sync import (
    results_pull_request_sync_sensor,
    sync_results_pull_requests,
    sync_results_pull_requests_job,
)
from app.models import PullRequestResult, ResultsRepository, Task
from app.tests.conftest import SAMPLE_SECRET

REPOSITORY = ResultsRepository(
    id=5, uri="gitea.fn.svc:4000/fn/results", provider="gitea",
    api_uri="http://gitea.fn.svc:4000/api/v1", secret=SAMPLE_SECRET, target_dir="results", project_id=1,
)
TASK = Task(
    id=7, name="t", docker_image="img", spec={}, attempt=1, requested_by="u", project_id=1, trigger_id=3,
)


def result(id=9, state="OPENED", number=3):
    opened = state != "PUSHED"
    return PullRequestResult(
        id=id, type="PR", task_id=7, results_repository_id=5, state=state, attempts=1,
        branch=f"branch-{id}", commit_sha="c", number=number if opened else None,
        url=f"http://g/pulls/{number}" if opened else None,
    )


def git_pr(state="open", merged_at=None, merge_commit_sha="test-merge", number=3):
    return {
        "number": number, "html_url": f"http://g/pulls/{number}", "state": state, "merged_at": merged_at,
        "merge_commit_sha": merge_commit_sha,
    }


def not_found(*args):
    response = requests.Response()
    response.status_code = 404
    raise requests.HTTPError("404 Not Found", response=response)


def sync(results, prs_by_number=None, prs_by_branch=None):
    backend_api = MagicMock()
    backend_api.get_results_by_state.return_value = results
    backend_api.get_task.return_value = TASK
    backend_api.get_results_repository.return_value = REPOSITORY
    git_api = MagicMock()
    git_api.get_pull_request.side_effect = lambda repo_path, number: (prs_by_number or {})[number]()
    git_api.get_default_branch.return_value = "main"
    git_api.find_pull_request_by_branch.side_effect = (
        lambda repo_path, branch, base: (prs_by_branch or {}).get(branch)
    )
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = dg.build_op_context(resources={"backend_api": backend_api, "git_apis": git_apis})
    sync_results_pull_requests(context)
    return backend_api, git_apis, git_api


def patched(backend_api):
    return {c.args[0]: c.args[1] for c in backend_api.patch_result.call_args_list}


def test_a_merged_pull_request_is_recorded():
    backend_api, git_apis, git_api = sync(
        [result()], {3: lambda: git_pr("closed", "2026-10-08T10:00:00Z", "m1")}
    )

    backend_api.get_results_by_state.assert_called_once_with(["PUSHED", "OPENED"])
    backend_api.get_results_repository.assert_called_once_with(1)
    git_apis.for_repository.assert_called_once_with(REPOSITORY)
    git_api.get_pull_request.assert_called_once_with("fn/results", 3)
    assert patched(backend_api) == {9: {
        "state": "MERGED", "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "m1",
    }}


def test_a_closed_pull_request_is_recorded_without_a_merge_commit():
    backend_api, _, _ = sync([result()], {3: lambda: git_pr("closed")})

    assert patched(backend_api) == {9: {"state": "CLOSED", "merged_at": None, "merge_commit_sha": None}}


def test_a_pull_request_still_open_is_left_alone():
    backend_api, _, _ = sync(
        [result(9, number=3), result(10, number=4)], {3: lambda: git_pr(), 4: lambda: git_pr("closed", number=4)}
    )

    assert list(patched(backend_api)) == [10]


def test_a_deleted_pull_request_is_skipped_and_the_others_still_synced():
    backend_api, _, _ = sync(
        [result(9, number=3), result(10, number=4)], {3: not_found, 4: lambda: git_pr("closed", number=4)}
    )

    assert list(patched(backend_api)) == [10]


def test_a_provider_error_other_than_404_fails_the_sync():
    def server_error(*args):
        response = requests.Response()
        response.status_code = 500
        raise requests.HTTPError("500", response=response)

    with pytest.raises(requests.HTTPError):
        sync([result()], {3: server_error})


def test_a_pushed_result_with_a_pull_request_records_it():
    backend_api, _, git_api = sync([result(9, "PUSHED")], prs_by_branch={"branch-9": git_pr(number=5)})

    git_api.get_default_branch.assert_called_once_with("fn/results")
    git_api.find_pull_request_by_branch.assert_called_once_with("fn/results", "branch-9", "main")
    git_api.get_pull_request.assert_not_called()
    assert patched(backend_api) == {9: {
        "number": 5, "url": "http://g/pulls/5", "state": "OPENED", "merged_at": None, "merge_commit_sha": None,
    }}


def test_a_pushed_result_whose_pull_request_is_merged_records_the_merge():
    backend_api, _, _ = sync(
        [result(9, "PUSHED")], prs_by_branch={"branch-9": git_pr("closed", "2026-10-08T10:00:00Z", "m1", number=5)}
    )

    assert patched(backend_api)[9]["state"] == "MERGED"
    assert patched(backend_api)[9]["merge_commit_sha"] == "m1"


def test_a_pushed_result_without_a_pull_request_is_left_alone():
    backend_api, _, _ = sync([result(9, "PUSHED")], prs_by_branch={})

    backend_api.patch_result.assert_not_called()


@pytest.mark.parametrize("state", ["UNKNOWN", "MERGED", "CLOSED"])
def test_results_in_other_states_are_ignored_when_the_backend_does_not_filter(state):
    backend_api, git_apis, _ = sync([result(8, state), result(10, number=4)], {4: lambda: git_pr("closed", number=4)})

    assert list(patched(backend_api)) == [10]
    backend_api.get_task.assert_called_once_with(7)


def run_sensor(results, in_flight=False):
    backend_api = MagicMock()
    backend_api.get_results_by_state.return_value = results
    context = MagicMock()
    context.resources.backend_api = backend_api
    context.instance.get_runs.return_value = [MagicMock()] if in_flight else []
    return results_pull_request_sync_sensor._raw_fn(context), context


@pytest.mark.parametrize("state", ["PUSHED", "OPENED"])
def test_the_sensor_requests_a_sync_when_results_are_pushed_or_opened(state):
    request, context = run_sensor([result(state=state)])

    assert isinstance(request, dg.RunRequest)
    assert re.fullmatch(r"sync-results-prs/\d{12}", request.run_key)
    filters = context.instance.get_runs.call_args.kwargs["filters"]
    assert filters.job_name == "sync_results_pull_requests_job"
    assert filters.statuses == IN_FLIGHT


def test_the_sensor_skips_when_nothing_is_pushed_or_opened():
    request, _ = run_sensor([])

    assert isinstance(request, dg.SkipReason)


def test_the_sensor_skips_results_the_backend_did_not_filter_out():
    request, _ = run_sensor([result(1, "UNKNOWN"), result(2, "MERGED"), result(3, "CLOSED")])

    assert isinstance(request, dg.SkipReason)


def test_the_sensor_skips_while_a_sync_is_in_flight():
    request, _ = run_sensor([result()], in_flight=True)

    assert isinstance(request, dg.SkipReason)


def test_the_sensor_defaults_to_stopped_and_targets_the_sync_job():
    assert results_pull_request_sync_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert results_pull_request_sync_sensor.job_name == "sync_results_pull_requests_job"
    assert results_pull_request_sync_sensor in SENSORS
    assert sync_results_pull_requests_job in JOBS
