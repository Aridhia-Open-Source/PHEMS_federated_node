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
from app.models import GitProvider, Project, ProjectResultsRepository, PullRequestResult, ResultsRepository
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


def not_found(*args):
    response = requests.Response()
    response.status_code = 404
    raise requests.HTTPError("404 Not Found", response=response)


def sync(results, prs_by_number=None, prs_by_branch=None, repository=REPOSITORY, patch_effect=None):
    backend_api = MagicMock()
    backend_api.patch_result.side_effect = patch_effect
    backend_api.get_projects.return_value = [Project(id=1, name="p")]
    backend_api.get_results_by_step.return_value = results
    backend_api.get_results_repository_by_id.return_value = repository
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
    return {c.args[1]: c.args[2] for c in backend_api.patch_result.call_args_list}


def test_a_merged_pull_request_is_recorded():
    backend_api, git_apis, git_api = sync(
        [result()], {3: lambda: git_pr("closed", "2026-10-08T10:00:00Z", "m1")}
    )

    backend_api.get_results_by_step.assert_called_once_with(1, ["PUSHED", "OPENED"])
    backend_api.get_results_repository_by_id.assert_called_once_with(1, 5)
    git_apis.for_repository.assert_called_once_with(GLOBAL_REPOSITORY)
    git_api.get_pull_request.assert_called_once_with("fn/results", 3)
    assert patched(backend_api) == {9: {
        "step": "MERGED", "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "m1",
    }}


def test_a_revoked_results_repository_is_still_synced():
    revoked = REPOSITORY.model_copy(update={"revoked": True, "active": False})

    backend_api, _, _ = sync([result()], {3: lambda: git_pr("closed", "2026-10-08T10:00:00Z", "m1")}, repository=revoked)

    assert patched(backend_api) == {9: {
        "step": "MERGED", "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "m1",
    }}


def test_a_result_is_synced_against_its_own_repository_fetched_once():
    other_global = GLOBAL_REPOSITORY.model_copy(update={"id": 3, "uri": "http://gitea.fn.svc:4000/fn/other"})
    other = REPOSITORY.model_copy(update={"id": 6, "results_repository": other_global})
    old = result(9).model_copy(update={"results_repository_id": 6})
    backend_api = MagicMock()
    backend_api.get_projects.return_value = [Project(id=1, name="p")]
    backend_api.get_results_by_step.return_value = [old, result(10, number=4), result(11, number=5)]
    backend_api.get_results_repository_by_id.side_effect = lambda project_id, id: {5: REPOSITORY, 6: other}[id]
    git_api = MagicMock()
    git_api.get_pull_request.side_effect = lambda repo_path, number: git_pr(number=number)
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = dg.build_op_context(resources={"backend_api": backend_api, "git_apis": git_apis})

    sync_results_pull_requests(context)

    assert [c.args for c in backend_api.get_results_repository_by_id.call_args_list] == [(1, 6), (1, 5)]
    backend_api.get_results_repository.assert_not_called()
    assert [c.args[0] for c in git_apis.for_repository.call_args_list] == [other_global, GLOBAL_REPOSITORY, GLOBAL_REPOSITORY]


def test_a_closed_pull_request_is_recorded_without_a_merge_commit():
    backend_api, _, _ = sync([result()], {3: lambda: git_pr("closed")})

    assert patched(backend_api) == {9: {"step": "CLOSED", "merged_at": None, "merge_commit_sha": None}}


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


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(str(status), response=response)


def test_a_409_on_a_result_is_skipped_and_the_others_still_synced():
    backend_api, _, _ = sync(
        [result(9, number=3), result(10, number=4)],
        {3: lambda: git_pr("closed", number=3), 4: lambda: git_pr("closed", number=4)},
        patch_effect=[http_error(409), None],
    )

    assert list(patched(backend_api)) == [9, 10]


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
        "number": 5, "url": "http://g/pulls/5", "state": "DELIVERED", "step": "OPENED", "merged_at": None,
        "merge_commit_sha": None,
    }}


def test_a_pushed_result_whose_pull_request_is_merged_records_the_merge():
    backend_api, _, _ = sync(
        [result(9, "PUSHED")], prs_by_branch={"branch-9": git_pr("closed", "2026-10-08T10:00:00Z", "m1", number=5)}
    )

    assert patched(backend_api)[9]["step"] == "MERGED"
    assert patched(backend_api)[9]["state"] == "DELIVERED"
    assert patched(backend_api)[9]["merge_commit_sha"] == "m1"


def test_a_pushed_result_without_a_pull_request_is_left_alone():
    backend_api, _, _ = sync([result(9, "PUSHED")], prs_by_branch={})

    backend_api.patch_result.assert_not_called()


def test_the_results_are_requested_by_step_of_each_project():
    backend_api, _, _ = sync([result()], {3: lambda: git_pr()})

    backend_api.get_results_by_step.assert_called_once_with(1, ["PUSHED", "OPENED"])


def run_sensor(results, in_flight=False):
    backend_api = MagicMock()
    backend_api.get_projects.return_value = [Project(id=1, name="p")]
    backend_api.get_results_by_step.return_value = results
    context = MagicMock()
    context.resources.backend_api = backend_api
    context.instance.get_runs.return_value = [MagicMock()] if in_flight else []
    return results_pull_request_sync_sensor._raw_fn(context), context


@pytest.mark.parametrize("step", ["PUSHED", "OPENED"])
def test_the_sensor_requests_a_sync_when_results_are_pushed_or_opened(step):
    request, context = run_sensor([result(step=step)])

    assert isinstance(request, dg.RunRequest)
    assert re.fullmatch(r"sync-results-prs/\d{12}", request.run_key)
    filters = context.instance.get_runs.call_args.kwargs["filters"]
    assert filters.job_name == "sync_results_pull_requests_job"
    assert filters.statuses == IN_FLIGHT


def test_the_sensor_skips_when_nothing_is_pushed_or_opened():
    request, _ = run_sensor([])

    assert isinstance(request, dg.SkipReason)
