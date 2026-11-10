import re
from unittest.mock import MagicMock, call

import pytest
import requests

import dagster as dg

from app.definitions.sensors.base import IN_FLIGHT
from app.definitions.sensors.task import JOBS, SENSORS
from app.definitions.sensors.task import pull_request_sync
from app.definitions.sensors.task.pull_request_sync import (
    ResultsPullRequestSyncSensor,
    open_results_pull_request,
    open_results_pull_request_job,
    results_pull_request_sync_sensor,
    sync_results_pull_requests,
    sync_results_pull_requests_job,
)
from app.delivery.results import MAX_ERROR_LENGTH
from app.models import (
    GitProvider,
    Project,
    ProjectResultsRepository,
    PullRequestResult,
    ResultsRepository,
    TaskTrigger,
    TriggerRepositoryRef,
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
    id=5, project_id=1, results_repository=GLOBAL_REPOSITORY, base_branch="main",
    target_dir="results", owned_by_federated_node=True, enabled=True, revoked=False, active=True,
)
TASK_TRIGGER = TaskTrigger(
    project_id=1, trigger_repository_id=2, number=12, title="t", raised_by="u", merged_at="2026-01-01T00:00:00Z",
    merge_commit_sha="abc", state="YIELDED", task_id=7, spec_files=["spec.json"], spec_raw="{}",
    trigger_repository=TriggerRepositoryRef(id=2, repo_path="fn/analysis", uri="gitea.fn.svc:3000/fn/analysis"),
)


def result(id=9, step="OPENED", number=3, attempts=0, created_at="2026-10-08 09:00:00", repository_id=5):
    opened = step != "PUSHED"
    return PullRequestResult(
        id=id, type="PR", task_id=7, project_id=1, results_repository_id=repository_id, step=step,
        state="DELIVERED", attempts=attempts, created_at=created_at,
        branch=f"branch-{id}", commit_sha="c", number=number if opened else None,
        url=f"http://g/pulls/{number}" if opened else None,
    )


def git_pr(state="open", merged_at=None, merge_commit_sha="test-merge", number=3, head="branch-9", base="main"):
    return {
        "number": number, "html_url": f"http://g/pulls/{number}", "state": state, "merged_at": merged_at,
        "merge_commit_sha": merge_commit_sha, "head": {"ref": head}, "base": {"ref": base},
    }


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(str(status), response=response)


def not_found(*args):
    raise http_error(404)


def server_error(*args):
    raise http_error(500)


def listed(pulls, repo_path):
    """What the provider lists for the repository: pulls is a list, or a dict of lists by repo_path, or a function that raises"""
    pulls = pulls[repo_path] if isinstance(pulls, dict) else pulls
    return pulls() if callable(pulls) else pulls


def sync_sensor(
    results, pulls=(), repositories=None, in_flight=None, base_branch="main", resource_deleted=False,
):
    """
    One tick of the sensor: what it yields, the backend, the git clients factory, the git client and the context.
    results are the OPENED ones, and the PUSHED ones, which the backend filters to the projects that open pull
    requests. in_flight names the job of a run in flight for any result.
    """
    backend_api = MagicMock()
    backend_api.get_projects.return_value = [Project(id=1, name="p")]
    backend_api.get_results_by_step.side_effect = lambda project_id, steps, **filters: [
        r for r in results if r.step.value in steps
    ]
    backend_api.get_results_repository_by_id.side_effect = (
        not_found if resource_deleted else lambda project_id, id: (repositories or {5: REPOSITORY})[id]
    )
    backend_api.get_task_config.return_value = {"config_snapshot": {"results": {"base_branch": base_branch}}}
    git_api = MagicMock()
    git_api.get_pulls.side_effect = lambda repo_path, since, state: listed(pulls, repo_path)
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = MagicMock()
    context.instance.get_runs.side_effect = lambda filters, limit: [MagicMock()] if filters.job_name == in_flight else []
    yielded = list(ResultsPullRequestSyncSensor(context=context, backend_api=backend_api, git_apis=git_apis)())
    return yielded, backend_api, git_apis, git_api, context


def run_requests(yielded):
    return [y for y in yielded if isinstance(y, dg.RunRequest)]


def patch_of(request):
    return request.run_config["ops"]["sync_results_pull_requests"]["config"]["patch"]


def test_an_opened_result_whose_pull_request_is_merged_launches_one_run_that_records_the_merge():
    yielded, backend_api, git_apis, git_api, _ = sync_sensor(
        [result()], [git_pr("closed", "2026-10-08T10:00:00Z", "m1", head="x")]
    )

    (request,) = yielded
    assert re.fullmatch(r"sync-result/9/MERGED/\d+", request.run_key)
    assert request.job_name == "sync_results_pull_requests_job"
    assert request.tags == {"trigger": "results-pr-sync", "result_id": "9"}
    assert request.run_config == {"ops": {"sync_results_pull_requests": {"config": {
        "project_id": 1, "result_id": 9,
        "patch": {
            "step": "MERGED", "number": 3, "url": "http://g/pulls/3", "merged_at": "2026-10-08T10:00:00Z",
            "merge_commit_sha": "m1",
        },
    }}}}
    backend_api.get_results_repository_by_id.assert_called_once_with(1, 5)
    git_apis.for_repository.assert_called_once_with(GLOBAL_REPOSITORY)
    git_api.get_pulls.assert_called_once_with("fn/results", since="2026-10-08T09:00:00Z", state="all")
    backend_api.get_task_config.assert_not_called()
    backend_api.patch_result.assert_not_called()


def test_an_opened_result_whose_pull_request_is_closed_launches_one_run_without_a_merge_commit():
    yielded, _, _, _, _ = sync_sensor([result()], [git_pr("closed")])

    (request,) = yielded
    assert re.fullmatch(r"sync-result/9/CLOSED/\d+", request.run_key)
    assert patch_of(request) == {
        "step": "CLOSED", "number": 3, "url": "http://g/pulls/3", "merged_at": None, "merge_commit_sha": None,
    }


def test_the_results_are_asked_of_the_backend_pushed_ones_only_of_the_projects_that_open_pull_requests():
    yielded, backend_api, git_apis, _, _ = sync_sensor([])

    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)
    assert backend_api.get_results_by_step.call_args_list == [
        call(1, ["PUSHED"], open_pull_requests=True), call(1, ["OPENED"]),
    ]
    # No result of another step is asked of the provider
    git_apis.for_repository.assert_not_called()


def test_a_pull_request_still_open_launches_no_run():
    yielded, _, _, _, _ = sync_sensor([result()], [git_pr()])

    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)


def test_an_opened_result_whose_pull_request_is_not_listed_launches_no_run():
    yielded, _, _, _, _ = sync_sensor([result()], [git_pr(number=4)])

    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)


def test_a_pushed_result_with_a_pull_request_launches_one_run_that_records_it_and_clears_the_attempts():
    yielded, backend_api, _, git_api, _ = sync_sensor(
        [result(9, "PUSHED", attempts=2)], [git_pr(number=5, base="release")], base_branch="release"
    )

    (request,) = yielded
    assert re.fullmatch(r"sync-result/9/OPENED/\d+", request.run_key)
    assert request.job_name == "sync_results_pull_requests_job"
    assert patch_of(request) == {
        "step": "OPENED", "number": 5, "url": "http://g/pulls/5", "merged_at": None, "merge_commit_sha": None,
        "attempts": 0, "error": None,
    }
    # The base branch is the task's pinned one: neither the repository's default nor the assignment's current one
    backend_api.get_task_config.assert_called_once_with(1, 7)
    git_api.get_default_branch.assert_not_called()
    git_api.create_pull_request.assert_not_called()


def test_a_pushed_result_whose_pull_request_is_merged_launches_one_run_that_records_the_merge():
    yielded, _, _, _, _ = sync_sensor(
        [result(9, "PUSHED")], [git_pr("closed", "2026-10-08T10:00:00Z", "m1", number=5)]
    )

    (request,) = yielded
    assert re.fullmatch(r"sync-result/9/MERGED/\d+", request.run_key)
    assert patch_of(request)["merge_commit_sha"] == "m1"


def test_a_pushed_result_without_a_pull_request_launches_the_open_job():
    yielded, backend_api, _, git_api, _ = sync_sensor([result(9, "PUSHED")], [], base_branch="release")

    (request,) = yielded
    assert re.fullmatch(r"open-result/9/OPENED/\d+", request.run_key)
    assert request.job_name == "open_results_pull_request_job"
    assert request.tags == {"trigger": "results-pr-sync", "result_id": "9"}
    assert request.run_config == {"ops": {"open_results_pull_request": {"config": {
        "project_id": 1, "result_id": 9, "task_id": 7, "results_repository_id": 5, "branch": "branch-9",
        "base_branch": "release", "attempts": 0,
    }}}}
    backend_api.get_task_config.assert_called_once_with(1, 7)
    git_api.create_pull_request.assert_not_called()
    backend_api.patch_result.assert_not_called()


@pytest.mark.parametrize("pr", [git_pr(head="other-branch"), git_pr(base="release")])
def test_a_pull_request_of_another_branch_or_into_another_base_is_not_the_results_pull_request(pr):
    yielded, _, _, _, _ = sync_sensor([result(9, "PUSHED")], [pr])

    (request,) = yielded
    assert request.job_name == "open_results_pull_request_job"


def test_the_open_job_carries_the_attempts_of_the_result():
    yielded, _, _, _, _ = sync_sensor([result(9, "PUSHED", attempts=2)], [])

    (request,) = yielded
    assert request.run_config["ops"]["open_results_pull_request"]["config"]["attempts"] == 2


def test_only_the_changed_results_launch_a_run_each():
    yielded, _, _, _, _ = sync_sensor(
        [result(9, number=3), result(10, number=4), result(11, number=5), result(12, "PUSHED"), result(13, "PUSHED")],
        [
            git_pr(number=3), git_pr("closed", number=4), git_pr("closed", "t", "m", number=5),
            git_pr(number=6, head="branch-12"),
        ],
    )

    assert [(r.job_name, re.sub(r"/\d+$", "", r.run_key)) for r in run_requests(yielded)] == [
        ("sync_results_pull_requests_job", "sync-result/12/OPENED"),
        ("open_results_pull_request_job", "open-result/13/OPENED"),
        ("sync_results_pull_requests_job", "sync-result/10/CLOSED"),
        ("sync_results_pull_requests_job", "sync-result/11/MERGED"),
    ]
    assert len(yielded) == 4


@pytest.mark.parametrize("job_name", ["sync_results_pull_requests_job", "open_results_pull_request_job"])
def test_a_result_with_a_run_of_either_job_in_flight_is_not_read_from_the_provider(job_name):
    yielded, _, git_apis, git_api, context = sync_sensor([result()], [git_pr("closed")], in_flight=job_name)

    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)
    git_apis.for_repository.assert_not_called()
    git_api.get_pulls.assert_not_called()
    runs = [c.kwargs["filters"] for c in context.instance.get_runs.call_args_list]
    assert job_name in [filters.job_name for filters in runs]
    assert all(filters.tags == {"trigger": "results-pr-sync", "result_id": "9"} for filters in runs)
    assert all(filters.statuses == IN_FLIGHT for filters in runs)


def test_several_results_of_a_repository_cost_one_provider_list_and_one_token_from_the_oldest_result():
    yielded, backend_api, git_apis, git_api, _ = sync_sensor(
        [
            result(9, created_at="2026-10-08 09:00:00"), result(10, number=4, created_at="2026-10-07 18:30:00"),
            result(11, "PUSHED", created_at="2026-10-09 07:00:00"), result(12, "PUSHED", created_at="2026-10-09 08:00:00"),
        ],
        [git_pr(number=3), git_pr("closed", number=4), git_pr(number=6, head="branch-11")],
    )

    assert len(run_requests(yielded)) == 3
    git_apis.for_repository.assert_called_once_with(GLOBAL_REPOSITORY)
    git_api.get_pulls.assert_called_once_with("fn/results", since="2026-10-07T18:30:00Z", state="all")
    backend_api.get_results_repository_by_id.assert_called_once_with(1, 5)


def test_a_result_is_synced_against_its_own_repository_listed_once():
    other_global = GLOBAL_REPOSITORY.model_copy(
        update={"id": 3, "uri": "http://gitea.fn.svc:4000/fn/other", "repo_path": "fn/other"}
    )
    other = REPOSITORY.model_copy(update={"id": 6, "results_repository": other_global})
    yielded, backend_api, git_apis, git_api, _ = sync_sensor(
        [result(9, repository_id=6), result(10, number=4), result(11, number=5)],
        {"fn/other": [git_pr("closed")], "fn/results": [git_pr("closed", number=4), git_pr("closed", number=5)]},
        repositories={5: REPOSITORY, 6: other},
    )

    assert [c.args for c in backend_api.get_results_repository_by_id.call_args_list] == [(1, 6), (1, 5)]
    assert [c.args[0] for c in git_apis.for_repository.call_args_list] == [other_global, GLOBAL_REPOSITORY]
    assert [c.args[0] for c in git_api.get_pulls.call_args_list] == ["fn/other", "fn/results"]
    assert len(run_requests(yielded)) == 3


def test_a_result_whose_attempts_ran_out_is_not_synced(monkeypatch):
    monkeypatch.setattr(pull_request_sync, "DELIVERY_MAX_ATTEMPTS", 3)

    yielded, _, _, _, _ = sync_sensor([result(9, "PUSHED", attempts=2), result(10, "PUSHED", attempts=3)], [])

    (request,) = yielded
    assert request.run_config["ops"]["open_results_pull_request"]["config"]["result_id"] == 9


def test_a_revoked_results_repository_is_still_synced():
    revoked = REPOSITORY.model_copy(update={"revoked": True, "active": False})

    yielded, _, _, _, _ = sync_sensor(
        [result()], [git_pr("closed", "2026-10-08T10:00:00Z", "m1")], repositories={5: revoked}
    )

    (request,) = yielded
    assert patch_of(request)["step"] == "MERGED"


def test_a_result_whose_resource_is_deleted_is_skipped():
    yielded, backend_api, git_apis, _, _ = sync_sensor([result(9), result(10, number=4)], resource_deleted=True)

    (skip,) = yielded
    assert isinstance(skip, dg.SkipReason)
    backend_api.get_results_repository_by_id.assert_called_once_with(1, 5)
    git_apis.for_repository.assert_not_called()


def test_a_provider_error_fails_the_tick_when_nothing_launches():
    with pytest.raises(RuntimeError, match="Results pull request sync failed for Results pull request of result 9"):
        sync_sensor([result()], server_error)


def test_a_provider_error_in_one_repository_does_not_stop_the_results_of_another():
    other_global = GLOBAL_REPOSITORY.model_copy(update={"id": 3, "repo_path": "fn/other"})
    other = REPOSITORY.model_copy(update={"id": 6, "results_repository": other_global})

    yielded, _, _, _, _ = sync_sensor(
        [result(9, repository_id=6), result(10, number=4)],
        {"fn/other": server_error, "fn/results": [git_pr("closed", number=4)]},
        repositories={5: REPOSITORY, 6: other},
    )

    (request,) = yielded
    assert re.fullmatch(r"sync-result/10/CLOSED/\d+", request.run_key)


def test_the_sensor_is_registered_with_the_backend_and_the_git_clients_and_both_jobs():
    assert results_pull_request_sync_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert results_pull_request_sync_sensor in SENSORS
    assert results_pull_request_sync_sensor.required_resource_keys == {"backend_api", "git_apis"}
    assert {job.name for job in results_pull_request_sync_sensor.jobs} == {
        "sync_results_pull_requests_job", "open_results_pull_request_job",
    }
    assert sync_results_pull_requests_job in JOBS
    assert open_results_pull_request_job in JOBS


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
        [result(9, "PUSHED")], [git_pr("closed", "2026-10-08T10:00:00Z", "m1", number=5)]
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
        "step": "MERGED", "number": 5, "url": "http://g/pulls/5", "merged_at": "2026-10-08T10:00:00Z",
        "merge_commit_sha": "m1", "attempts": 0, "error": None,
    })


def open_run(create_effect=None, attempts=0):
    backend_api = MagicMock()
    backend_api.get_global_results_repository.return_value = GLOBAL_REPOSITORY
    backend_api.get_task_trigger.return_value = TASK_TRIGGER
    git_api = MagicMock()
    git_api.create_pull_request.side_effect = create_effect
    git_api.create_pull_request.return_value = git_pr(number=8, head="branch-9")
    git_apis = MagicMock()
    git_apis.for_repository.return_value = git_api
    context = dg.build_op_context(
        resources={"backend_api": backend_api, "git_apis": git_apis},
        op_config={
            "project_id": 1, "result_id": 9, "task_id": 7, "results_repository_id": 2, "branch": "branch-9",
            "base_branch": "release", "attempts": attempts,
        },
    )
    return context, backend_api, git_apis, git_api


def test_the_open_op_opens_the_pull_request_and_records_it_clearing_the_attempts_and_error():
    context, backend_api, git_apis, git_api = open_run()

    open_results_pull_request(context)

    git_apis.for_repository.assert_called_once_with(GLOBAL_REPOSITORY, 1)
    backend_api.get_task_trigger.assert_called_once_with(1, 7)
    git_api.create_pull_request.assert_called_once_with(
        "fn/results", "branch-9", "release", "fn/analysis PR12 - task 7 - results",
        "Results of the task run for pull request #12, merged at abc.",
    )
    backend_api.patch_result.assert_called_once_with(1, 9, {
        "step": "OPENED", "number": 8, "url": "http://g/pulls/8", "merged_at": None, "merge_commit_sha": None,
        "attempts": 0, "error": None,
    })


def test_a_failed_opening_counts_an_attempt_and_records_the_error_without_touching_the_state_or_step_and_raises():
    context, backend_api, _, _ = open_run(RuntimeError("provider down"), attempts=1)

    with pytest.raises(RuntimeError, match="provider down"):
        open_results_pull_request(context)

    backend_api.patch_result.assert_called_once_with(1, 9, {"attempts": 2, "error": "RuntimeError: provider down"})


def test_a_failed_opening_cuts_a_long_error():
    context, backend_api, _, _ = open_run(RuntimeError("x" * 5000))

    with pytest.raises(RuntimeError):
        open_results_pull_request(context)

    assert len(backend_api.patch_result.call_args.args[2]["error"]) == MAX_ERROR_LENGTH


def test_a_refused_token_counts_as_a_failed_opening():
    context, backend_api, git_apis, git_api = open_run()
    git_apis.for_repository.side_effect = http_error(403)

    with pytest.raises(requests.HTTPError):
        open_results_pull_request(context)

    git_api.create_pull_request.assert_not_called()
    assert backend_api.patch_result.call_args.args[2]["attempts"] == 1


def test_the_run_config_of_the_sensor_is_accepted_by_the_open_job_and_opens_the_pull_request():
    yielded, _, _, _, _ = sync_sensor([result(9, "PUSHED")], [], base_branch="release")
    (request,) = yielded
    backend_api = MagicMock()
    backend_api.get_global_results_repository.return_value = GLOBAL_REPOSITORY
    backend_api.get_task_trigger.return_value = TASK_TRIGGER
    git_apis = MagicMock()
    git_apis.for_repository.return_value.create_pull_request.return_value = git_pr(number=8)
    definitions = dg.Definitions(
        jobs=[open_results_pull_request_job], resources={"backend_api": backend_api, "git_apis": git_apis}
    )

    with dg.DagsterInstance.ephemeral() as instance:
        run = definitions.resolve_job_def("open_results_pull_request_job").execute_in_process(
            run_config=request.run_config, instance=instance
        )

    assert run.success
    git_apis.for_repository.return_value.create_pull_request.assert_called_once()
    assert backend_api.patch_result.call_args.args[:2] == (1, 9)
    assert backend_api.patch_result.call_args.args[2]["step"] == "OPENED"
