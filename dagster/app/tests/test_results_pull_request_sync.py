import re
from unittest.mock import MagicMock

import pytest
import requests

import dagster as dg

from app.definitions.sensors.base import IN_FLIGHT
from app.definitions.sensors.task import JOBS, SENSORS
from app.definitions.sensors.task.pull_request_sync import (
    SYNCED,
    ResultsPullRequestSyncSensor,
    results_pull_request_sync_sensor,
    sync_results_pull_requests,
    sync_results_pull_requests_job,
)
from app.models import (
    GitProvider,
    Project,
    ProjectResultsRepository,
    PullRequestResult,
    PullRequestResultStep,
    ResultsRepository,
)
from app.tests.conftest import SAMPLE_SECRET

GLOBAL_REPOSITORY = ResultsRepository(
    id=2, uri="http://gitea.fn.svc:4000/fn/results", repo_path="fn/results",
    provider=GitProvider(
        id=1, name="gitea", type="gitea", uri="http://gitea.fn.svc:4000", api_uri="http://gitea.fn.svc:4000/api/v1",
        enabled=True,
    ),
    secret=SAMPLE_SECRET, enabled=True,
)
REPOSITORY = ProjectResultsRepository(
    id=5, project_id=1, results_repository=GLOBAL_REPOSITORY, target_dir="results",
    owned_by_federated_node=True, enabled=True, revoked=False, active=True,
)


def result(id=9, step="OPENED", number=3):
    opened = step != "PUSHED"
    return PullRequestResult(
        id=id, type="PR", task_id=7, project_id=1, results_repository_id=5, step=step,
        state="DELIVERED" if opened else "IN_PROGRESS", attempts=1,
        branch=f"branch-{id}", commit_sha="c", number=number if opened else None,
        url=f"http://g/pulls/{number}" if opened else None,
    )


def git_pr(state="open", merged_at=None, merge_commit_sha="test-merge", number=3):
    return {
        "number": number, "html_url": f"http://g/pulls/{number}", "state": state, "merged_at": merged_at,
        "merge_commit_sha": merge_commit_sha,
    }


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(str(status), response=response)


def not_found(*args):
    raise http_error(404)


def server_error(*args):
    raise http_error(500)


def sync_sensor(results, prs_by_number=None, prs_by_branch=None, repositories=None, in_flight=False):
    """One tick of the sensor: what it yields, the backend, the git clients factory, the git client and the context"""
    backend_api = MagicMock()
    backend_api.get_projects.return_value = [Project(id=1, name="p")]
    backend_api.get_results_by_step.return_value = results
    backend_api.get_results_repository_by_id.side_effect = (
        lambda project_id, id: (repositories or {5: REPOSITORY})[id]
    )
    git_api = MagicMock()
    git_api.get_pull_request.side_effect = lambda repo_path, number: (prs_by_number or {})[number]()
    git_api.get_default_branch.return_value = "main"
    git_api.find_pull_request_by_branch.side_effect = (
        lambda repo_path, branch, base: (prs_by_branch or {}).get(branch)
    )
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = MagicMock()
    context.instance.get_runs.return_value = [MagicMock()] if in_flight else []
    yielded = list(ResultsPullRequestSyncSensor(context=context, backend_api=backend_api, git_apis=git_apis)())
    return yielded, backend_api, git_apis, git_api, context


def run_requests(yielded):
    return [y for y in yielded if isinstance(y, dg.RunRequest)]


def patch_of(request):
    return request.run_config["ops"]["sync_results_pull_requests"]["config"]["patch"]


def test_an_opened_result_whose_pull_request_is_merged_launches_one_run_that_records_the_merge():
    yielded, backend_api, git_apis, git_api, _ = sync_sensor(
        [result()], {3: lambda: git_pr("closed", "2026-10-08T10:00:00Z", "m1")}
    )

    (request,) = yielded
    assert re.fullmatch(r"sync-result/9/MERGED/\d+", request.run_key)
    assert request.tags == {"trigger": "results-pr-sync", "result_id": "9"}
    assert request.run_config == {"ops": {"sync_results_pull_requests": {"config": {
        "project_id": 1, "result_id": 9,
        "patch": {"step": "MERGED", "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "m1"},
    }}}}
    backend_api.get_results_by_step.assert_called_once_with(1, ["PUSHED", "OPENED"])
    backend_api.get_results_repository_by_id.assert_called_once_with(1, 5)
    git_apis.for_repository.assert_called_once_with(GLOBAL_REPOSITORY)
    git_api.get_pull_request.assert_called_once_with("fn/results", 3)
    backend_api.patch_result.assert_not_called()


def test_an_opened_result_whose_pull_request_is_closed_launches_one_run_without_a_merge_commit():
    yielded, _, _, _, _ = sync_sensor([result()], {3: lambda: git_pr("closed")})

    (request,) = yielded
    assert re.fullmatch(r"sync-result/9/CLOSED/\d+", request.run_key)
    assert patch_of(request) == {"step": "CLOSED", "merged_at": None, "merge_commit_sha": None}


def test_a_pushed_result_with_a_pull_request_launches_one_run_that_records_it():
    yielded, _, _, git_api, _ = sync_sensor([result(9, "PUSHED")], prs_by_branch={"branch-9": git_pr(number=5)})

    (request,) = yielded
    assert re.fullmatch(r"sync-result/9/OPENED/\d+", request.run_key)
    assert patch_of(request) == {
        "number": 5, "url": "http://g/pulls/5", "state": "DELIVERED", "step": "OPENED", "merged_at": None,
        "merge_commit_sha": None,
    }
    git_api.get_default_branch.assert_called_once_with("fn/results")
    git_api.find_pull_request_by_branch.assert_called_once_with("fn/results", "branch-9", "main")
    git_api.get_pull_request.assert_not_called()


def test_a_pushed_result_whose_pull_request_is_merged_launches_one_run_that_records_the_merge():
    yielded, _, _, _, _ = sync_sensor(
        [result(9, "PUSHED")], prs_by_branch={"branch-9": git_pr("closed", "2026-10-08T10:00:00Z", "m1", number=5)}
    )

    (request,) = yielded
    assert re.fullmatch(r"sync-result/9/MERGED/\d+", request.run_key)
    assert patch_of(request)["state"] == "DELIVERED"
    assert patch_of(request)["merge_commit_sha"] == "m1"


def test_a_pull_request_still_open_launches_no_run():
    yielded, _, _, _, _ = sync_sensor([result()], {3: lambda: git_pr()})

    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)


def test_a_pushed_result_without_a_pull_request_launches_no_run():
    yielded, _, _, _, _ = sync_sensor([result(9, "PUSHED")], prs_by_branch={})

    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)


def test_only_the_changed_results_launch_a_run_each():
    yielded, _, _, _, _ = sync_sensor(
        [result(9, number=3), result(10, number=4), result(11, number=5), result(12, "PUSHED")],
        {3: lambda: git_pr(), 4: lambda: git_pr("closed", number=4), 5: lambda: git_pr("closed", "t", "m", number=5)},
        prs_by_branch={"branch-12": git_pr(number=6)},
    )

    assert [re.sub(r"/\d+$", "", r.run_key) for r in run_requests(yielded)] == [
        "sync-result/10/CLOSED", "sync-result/11/MERGED", "sync-result/12/OPENED"
    ]
    assert len(yielded) == 3


def test_a_result_with_a_run_in_flight_is_not_read_from_the_provider():
    yielded, _, git_apis, git_api, context = sync_sensor(
        [result()], {3: lambda: git_pr("closed")}, in_flight=True
    )

    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)
    git_apis.for_repository.assert_not_called()
    git_api.get_pull_request.assert_not_called()
    filters = context.instance.get_runs.call_args.kwargs["filters"]
    assert filters.job_name == "sync_results_pull_requests_job"
    assert filters.tags == {"trigger": "results-pr-sync", "result_id": "9"}
    assert filters.statuses == IN_FLIGHT


def test_a_result_is_synced_against_its_own_repository_fetched_once():
    other_global = GLOBAL_REPOSITORY.model_copy(update={"id": 3, "uri": "http://gitea.fn.svc:4000/fn/other"})
    other = REPOSITORY.model_copy(update={"id": 6, "results_repository": other_global})
    old = result(9).model_copy(update={"results_repository_id": 6})
    yielded, backend_api, git_apis, _, _ = sync_sensor(
        [old, result(10, number=4), result(11, number=5)],
        {3: lambda: git_pr("closed"), 4: lambda: git_pr("closed", number=4), 5: lambda: git_pr("closed", number=5)},
        repositories={5: REPOSITORY, 6: other},
    )

    assert [c.args for c in backend_api.get_results_repository_by_id.call_args_list] == [(1, 6), (1, 5)]
    assert [c.args[0] for c in git_apis.for_repository.call_args_list] == [other_global, GLOBAL_REPOSITORY, GLOBAL_REPOSITORY]
    assert len(run_requests(yielded)) == 3


def test_a_revoked_results_repository_is_still_synced():
    revoked = REPOSITORY.model_copy(update={"revoked": True, "active": False})

    yielded, _, _, _, _ = sync_sensor(
        [result()], {3: lambda: git_pr("closed", "2026-10-08T10:00:00Z", "m1")}, repositories={5: revoked}
    )

    (request,) = yielded
    assert patch_of(request)["step"] == "MERGED"


def test_a_result_whose_resource_is_deleted_is_skipped():
    backend_api = MagicMock()
    backend_api.get_projects.return_value = [Project(id=1, name="p")]
    backend_api.get_results_by_step.return_value = [result(9), result(10, number=4)]
    backend_api.get_results_repository_by_id.side_effect = not_found
    git_apis = MagicMock()
    context = MagicMock()
    context.instance.get_runs.return_value = []

    (skip,) = ResultsPullRequestSyncSensor(context=context, backend_api=backend_api, git_apis=git_apis)()

    assert isinstance(skip, dg.SkipReason)
    backend_api.get_results_repository_by_id.assert_called_once_with(1, 5)
    git_apis.for_repository.assert_not_called()


def test_a_deleted_pull_request_is_skipped_and_the_others_still_launch():
    yielded, _, _, _, _ = sync_sensor(
        [result(9, number=3), result(10, number=4)], {3: not_found, 4: lambda: git_pr("closed", number=4)}
    )

    (request,) = yielded
    assert re.fullmatch(r"sync-result/10/CLOSED/\d+", request.run_key)


def test_a_provider_error_other_than_404_fails_the_tick_when_nothing_launches():
    with pytest.raises(RuntimeError, match="Results pull request sync failed for Results pull request of result 9"):
        sync_sensor([result()], {3: server_error})


def test_a_provider_error_other_than_404_does_not_stop_the_other_results():
    yielded, _, _, _, _ = sync_sensor(
        [result(9, number=3), result(10, number=4)], {3: server_error, 4: lambda: git_pr("closed", number=4)}
    )

    (request,) = yielded
    assert re.fullmatch(r"sync-result/10/CLOSED/\d+", request.run_key)


def test_only_pushed_and_opened_results_are_synced_so_a_closed_one_reopened_stays_closed():
    assert SYNCED == [PullRequestResultStep.PUSHED, PullRequestResultStep.OPENED]
    # The backend returns no CLOSED result, so the provider is not asked about its pull request
    yielded, backend_api, git_apis, git_api, _ = sync_sensor([])
    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)
    backend_api.get_results_by_step.assert_called_once_with(1, ["PUSHED", "OPENED"])
    git_apis.for_repository.assert_not_called()
    git_api.get_pull_request.assert_not_called()


def test_the_sensor_is_registered_with_the_backend_and_the_git_clients():
    assert results_pull_request_sync_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert results_pull_request_sync_sensor in SENSORS
    assert results_pull_request_sync_sensor.required_resource_keys == {"backend_api", "git_apis"}
    assert sync_results_pull_requests_job in JOBS


def sync_run(patch, patch_effect=None):
    backend_api = MagicMock()
    backend_api.patch_result.side_effect = patch_effect
    context = dg.build_op_context(
        resources={"backend_api": backend_api},
        op_config={"project_id": 1, "result_id": 9, "patch": patch},
    )
    sync_results_pull_requests(context)
    return backend_api


def test_the_op_patches_the_result_it_was_given():
    patch = {"step": "MERGED", "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "m1"}

    backend_api = sync_run(patch)

    backend_api.patch_result.assert_called_once_with(1, 9, patch)


def test_a_409_on_the_result_is_skipped():
    backend_api = sync_run({"step": "CLOSED", "merged_at": None, "merge_commit_sha": None}, [http_error(409)])

    backend_api.patch_result.assert_called_once()


def test_a_backend_error_other_than_409_fails_the_run():
    with pytest.raises(requests.HTTPError):
        sync_run({"step": "CLOSED", "merged_at": None, "merge_commit_sha": None}, [http_error(500)])


def test_the_run_config_of_the_sensor_is_accepted_by_the_job_and_patches_the_result():
    yielded, _, _, _, _ = sync_sensor(
        [result(9, "PUSHED")], prs_by_branch={"branch-9": git_pr("closed", "2026-10-08T10:00:00Z", "m1", number=5)}
    )
    (request,) = yielded
    backend_api = MagicMock()
    definitions = dg.Definitions(jobs=[sync_results_pull_requests_job], resources={"backend_api": backend_api})

    with dg.DagsterInstance.ephemeral() as instance:
        run = definitions.resolve_job_def("sync_results_pull_requests_job").execute_in_process(
            run_config=request.run_config, instance=instance
        )

    assert run.success
    backend_api.patch_result.assert_called_once_with(1, 9, {
        "number": 5, "url": "http://g/pulls/5", "state": "DELIVERED", "step": "MERGED",
        "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "m1",
    })
