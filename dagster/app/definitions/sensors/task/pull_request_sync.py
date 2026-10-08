from datetime import datetime, timezone
from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, SensorEvaluationContext

from app.backend import BackendAPI
from app.definitions.sensors.git.base import GitAPIFactory
from app.definitions.sensors.git.pr_evaluate import IN_FLIGHT
from app.models import PullRequestResultState

MIN_SENSOR_INTERVAL_SECONDS = 10


@dg.op(required_resource_keys={"backend_api", "git_apis"})
def sync_results_pull_requests(context: OpExecCtx):
    """
    Ask the git provider for the state of every OPEN results pull request and record
    the state, merged_at and merge_commit_sha of the ones that changed.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    git_apis = cast(GitAPIFactory, context.resources.git_apis)
    for result in backend_api.get_task_results_by_pull_request_state(PullRequestResultState.OPEN.value):
        repository = backend_api.get_results_repository(backend_api.get_task(result.task_id).project_id)
        pr = git_apis.for_repository(repository).get_pull_request(repository.repo_path, result.pull_request_number)
        state = PullRequestResultState.from_git(pr)
        if state == result.pull_request_state:
            continue
        context.log.info(f"Results pull request {result.pull_request_url} is {state.value}")
        backend_api.patch_task_result(result.id, {
            "pull_request_state": state.value,
            "merged_at": pr["merged_at"],
            # GitHub fills merge_commit_sha on an unmerged PR with its test merge
            "merge_commit_sha": pr["merge_commit_sha"] if state == PullRequestResultState.MERGED else None,
        })


@dg.job
def sync_results_pull_requests_job():
    """Record the state of the open results pull requests."""
    sync_results_pull_requests()


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"backend_api"},
    job=sync_results_pull_requests_job,
)
def results_pull_request_sync_sensor(context: SensorEvaluationContext):
    """
    Launch sync_results_pull_requests_job when there are OPEN results pull requests,
    unless a run of it is in flight. The run key includes the minute, as the evaluate sensor's.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    if not backend_api.get_task_results_by_pull_request_state(PullRequestResultState.OPEN.value):
        return dg.SkipReason("No open results pull requests.")
    in_flight = context.instance.get_runs(
        filters=dg.RunsFilter(job_name=sync_results_pull_requests_job.name, statuses=IN_FLIGHT),
        limit=1,
    )
    if in_flight:
        return dg.SkipReason("A sync of the results pull requests is in flight.")
    minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    return dg.RunRequest(run_key=f"sync-results-prs/{minute}")
