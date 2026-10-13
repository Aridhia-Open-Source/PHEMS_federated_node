"""
Reconciles the results pull requests with the git provider. It heals one failure only: a
pull request opened, or merged or closed, that its result does not record. A failed delivery
is not retried here, see app.delivery.results.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import cast

import dagster as dg
import requests
from dagster import OpExecutionContext as OpExecCtx, SensorEvaluationContext

from app.backend import BackendAPI
from app.definitions.sensors.git.base import GitAPIFactory
from app.definitions.sensors.git.pr_evaluate import IN_FLIGHT
from app.models import PullRequestResult, PullRequestResultState

MIN_SENSOR_INTERVAL_SECONDS = 10
# PUSHED may have a pull request its result missed, OPENED may be merged or closed since.
SYNCED = [PullRequestResultState.PUSHED, PullRequestResultState.OPENED]


def get_synced_results(backend_api: BackendAPI) -> list[PullRequestResult]:
    """
    The results to sync. Filtered here as well: a backend that does not know the state
    filter ignores it and returns every result.
    """
    results = backend_api.get_results_by_state([state.value for state in SYNCED])
    return [result for result in results if result.state in SYNCED]


@dg.op(required_resource_keys={"backend_api", "git_apis"})
def sync_results_pull_requests(context: OpExecCtx):
    """
    Record what the git provider says of the results pull requests:
    - PUSHED: look the pull request up by the result's branch, and record its number, url and
      state if there is one. None is left alone.
    - OPENED: record the state of the pull request when it changed, MERGED or CLOSED.
      One deleted on the provider (404) is logged and skipped, not guessed CLOSED.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    git_apis = cast(GitAPIFactory, context.resources.git_apis)
    for result in get_synced_results(backend_api):
        repository = backend_api.get_results_repository(backend_api.get_task(result.task_id).project_id)
        git_api = git_apis.for_repository(repository)
        if result.state == PullRequestResultState.PUSHED:
            base_branch = git_api.get_default_branch(repository.repo_path)
            pr = git_api.find_pull_request_by_branch(repository.repo_path, result.branch, base_branch)
            if pr is None:
                continue
            found = {"number": pr["number"], "url": pr["html_url"]}
        else:
            try:
                pr = git_api.get_pull_request(repository.repo_path, result.number)
            except requests.HTTPError as e:
                if e.response.status_code != HTTPStatus.NOT_FOUND:
                    raise
                context.log.warning(f"Results pull request {result.url} is not found, skipped")
                continue
            found = {}
        state = PullRequestResultState.from_git(pr)
        if not found and state == result.state:
            continue
        context.log.info(f"Results pull request {pr['html_url']} is {state.value}")
        backend_api.patch_result(result.id, {
            **found,
            "state": state.value,
            "merged_at": pr["merged_at"],
            # GitHub fills merge_commit_sha on an unmerged PR with its test merge
            "merge_commit_sha": pr["merge_commit_sha"] if state == PullRequestResultState.MERGED else None,
        })


@dg.job
def sync_results_pull_requests_job():
    """Record the state of the pushed and opened results pull requests."""
    sync_results_pull_requests()


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"backend_api"},
    job=sync_results_pull_requests_job,
)
def results_pull_request_sync_sensor(context: SensorEvaluationContext):
    """
    Launch sync_results_pull_requests_job when there are PUSHED or OPENED results, unless a
    run of it is in flight. The run key includes the minute, as the evaluate sensor's.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    if not get_synced_results(backend_api):
        return dg.SkipReason("No pushed or opened results.")
    in_flight = context.instance.get_runs(
        filters=dg.RunsFilter(job_name=sync_results_pull_requests_job.name, statuses=IN_FLIGHT),
        limit=1,
    )
    if in_flight:
        return dg.SkipReason("A sync of the results pull requests is in flight.")
    minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    return dg.RunRequest(run_key=f"sync-results-prs/{minute}")
