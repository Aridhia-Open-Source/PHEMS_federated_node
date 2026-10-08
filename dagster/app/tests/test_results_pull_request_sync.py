import re
from unittest.mock import MagicMock

import dagster as dg

from app.definitions.sensors.git.pr_evaluate import IN_FLIGHT
from app.definitions.sensors.task import JOBS, SENSORS
from app.definitions.sensors.task.pull_request_sync import (
    results_pull_request_sync_sensor,
    sync_results_pull_requests,
    sync_results_pull_requests_job,
)
from app.models import ResultsRepository, Task, TaskResult
from app.tests.conftest import SAMPLE_SECRET

REPOSITORY = ResultsRepository(
    id=5, uri="gitea.fn.svc:4000/fn/results", provider="gitea",
    api_uri="http://gitea.fn.svc:4000/api/v1", secret=SAMPLE_SECRET, target_dir="results", project_id=1,
)
TASK = Task(
    id=7, name="t", docker_image="img", spec={}, attempt=1, requested_by="u", project_id=1, trigger_id=3,
)


def open_result(id=9, number=3):
    return TaskResult(
        id=id, type="PR", task_id=7, results_repository_id=5, status="DELIVERED", attempts=1,
        branch="b", commit_sha="c", number=number, url=f"http://g/pulls/{number}",
        merge_status="OPEN",
    )


def git_pr(state="open", merged_at=None, merge_commit_sha="test-merge"):
    return {"state": state, "merged_at": merged_at, "merge_commit_sha": merge_commit_sha}


def sync(results, prs_by_number):
    backend_api = MagicMock()
    backend_api.get_task_results_by_merge_status.return_value = results
    backend_api.get_task.return_value = TASK
    backend_api.get_results_repository.return_value = REPOSITORY
    git_api = MagicMock()
    git_api.get_pull_request.side_effect = lambda repo_path, number: prs_by_number[number]
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = dg.build_op_context(resources={"backend_api": backend_api, "git_apis": git_apis})
    sync_results_pull_requests(context)
    return backend_api, git_apis, git_api


def test_a_merged_pull_request_is_recorded():
    backend_api, git_apis, git_api = sync(
        [open_result()], {3: git_pr("closed", "2026-10-08T10:00:00Z", "m1")}
    )

    backend_api.get_task_results_by_merge_status.assert_called_once_with("OPEN")
    backend_api.get_results_repository.assert_called_once_with(1)
    git_apis.for_repository.assert_called_once_with(REPOSITORY)
    git_api.get_pull_request.assert_called_once_with("fn/results", 3)
    backend_api.patch_task_result.assert_called_once_with(9, {
        "merge_status": "MERGED", "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "m1",
    })


def test_a_closed_pull_request_is_recorded_without_a_merge_commit():
    backend_api, _, _ = sync([open_result()], {3: git_pr("closed")})

    backend_api.patch_task_result.assert_called_once_with(9, {
        "merge_status": "CLOSED", "merged_at": None, "merge_commit_sha": None,
    })


def test_a_pull_request_still_open_is_left_alone():
    backend_api, _, _ = sync([open_result(9, 3), open_result(10, 4)], {3: git_pr(), 4: git_pr("closed")})

    assert [c.args[0] for c in backend_api.patch_task_result.call_args_list] == [10]


def run_sensor(results, in_flight=False):
    backend_api = MagicMock()
    backend_api.get_task_results_by_merge_status.return_value = results
    context = MagicMock()
    context.resources.backend_api = backend_api
    context.instance.get_runs.return_value = [MagicMock()] if in_flight else []
    return results_pull_request_sync_sensor._raw_fn(context), context


def test_the_sensor_requests_a_sync_when_pull_requests_are_open():
    result, context = run_sensor([open_result()])

    assert isinstance(result, dg.RunRequest)
    assert re.fullmatch(r"sync-results-prs/\d{12}", result.run_key)
    filters = context.instance.get_runs.call_args.kwargs["filters"]
    assert filters.job_name == "sync_results_pull_requests_job"
    assert filters.statuses == IN_FLIGHT


def test_the_sensor_skips_when_nothing_is_open():
    result, _ = run_sensor([])

    assert isinstance(result, dg.SkipReason)


def test_the_sensor_skips_while_a_sync_is_in_flight():
    result, _ = run_sensor([open_result()], in_flight=True)

    assert isinstance(result, dg.SkipReason)


def test_the_sensor_defaults_to_stopped_and_targets_the_sync_job():
    assert results_pull_request_sync_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert results_pull_request_sync_sensor.job_name == "sync_results_pull_requests_job"
    assert results_pull_request_sync_sensor in SENSORS
    assert sync_results_pull_requests_job in JOBS
