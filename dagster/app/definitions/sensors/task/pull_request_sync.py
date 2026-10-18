"""
Reconciles the results pull requests with the git provider. It heals one failure only: a
pull request opened, or merged or closed, that its result does not record. A failed delivery
is not retried here, see app.delivery.results.
"""
from http import HTTPStatus
from typing import cast

import requests
import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, SensorEvaluationContext

from app.backend import BackendAPI
from app.config import DEFAULT_SENSOR_STATUS, MIN_SENSOR_INTERVAL_SECONDS
from app.definitions.sensors.base import run_in_flight, run_key
from app.definitions.sensors.git.base import GitAPIFactory
from app.models import PullRequestResult, PullRequestResultStep, ResultState

# PUSHED may have a pull request its result missed, OPENED may be merged or closed since.
SYNCED = [PullRequestResultStep.PUSHED, PullRequestResultStep.OPENED]


def get_synced_results(backend_api: BackendAPI) -> list[PullRequestResult]:
    """The results to sync, of every project: the backend filters them by step."""
    return [
        result
        for project in backend_api.get_projects()
        for result in backend_api.get_results_by_step(project.id, [step.value for step in SYNCED])
    ]


@dg.op(required_resource_keys={"backend_api", "git_apis"})
def sync_results_pull_requests(context: OpExecCtx):
    """
    Record what the git provider says of the results pull requests:
    - PUSHED: look the pull request up by the result's branch, and record its number, url and
      step if there is one, with the state DELIVERED. None is left alone.
    - OPENED: record the step of the pull request when it changed, MERGED or CLOSED.
      One deleted on the provider (404) is logged and skipped, not guessed CLOSED.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    git_apis = cast(GitAPIFactory, context.resources.git_apis)
    repositories = {}
    for result in get_synced_results(backend_api):
        # The repository the result was delivered to, which may not be the project's current one
        if result.results_repository_id not in repositories:
            repositories[result.results_repository_id] = backend_api.get_results_repository_by_id(
                result.project_id, result.results_repository_id
            ).results_repository
        repository = repositories[result.results_repository_id]
        git_api = git_apis.for_repository(repository)
        if result.step == PullRequestResultStep.PUSHED:
            base_branch = git_api.get_default_branch(repository.repo_path)
            pr = git_api.find_pull_request_by_branch(repository.repo_path, result.branch, base_branch)
            if pr is None:
                continue
            found = {"number": pr["number"], "url": pr["html_url"], "state": ResultState.DELIVERED.value}
        else:
            try:
                pr = git_api.get_pull_request(repository.repo_path, result.number)
            except requests.HTTPError as e:
                if e.response.status_code != HTTPStatus.NOT_FOUND:
                    raise
                context.log.warning(f"Results pull request {result.url} is not found, skipped")
                continue
            found = {}
        step = PullRequestResultStep.from_git(pr)
        if not found and step == result.step:
            continue
        context.log.info(f"Results pull request {pr['html_url']} is {step.value}")
        backend_api.patch_result(result.project_id, result.id, {
            **found,
            "step": step.value,
            "merged_at": pr["merged_at"],
            # GitHub fills merge_commit_sha on an unmerged PR with its test merge
            "merge_commit_sha": pr["merge_commit_sha"] if step == PullRequestResultStep.MERGED else None,
        })


@dg.job
def sync_results_pull_requests_job():
    """Record the step of the pushed and opened results pull requests."""
    sync_results_pull_requests()  # pylint: disable=no-value-for-parameter  # Dagster injects context


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=DEFAULT_SENSOR_STATUS,
    required_resource_keys={"backend_api"},
    job=sync_results_pull_requests_job,
)
def results_pull_request_sync_sensor(context: SensorEvaluationContext):
    """
    Launch sync_results_pull_requests_job when there are PUSHED or OPENED results, unless a
    run of it is in flight. The run key has no state, only the retry interval's slot, see run_key.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    if not get_synced_results(backend_api):
        return dg.SkipReason("No pushed or opened results.")
    if run_in_flight(context, sync_results_pull_requests_job, {}):
        return dg.SkipReason("A sync of the results pull requests is in flight.")
    return dg.RunRequest(run_key=run_key("sync-results-prs"))
