"""
Reconciles the results pull requests with the git provider. It heals one failure only: a
pull request opened, or merged or closed, that its result does not record. The sensor reads the
provider and launches a run only for a result whose pull request changed. A failed delivery
is not retried here, see app.delivery.results.
"""
from http import HTTPStatus
from typing import cast

import requests
import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, SensorEvaluationContext

from app.backend import BackendAPI
from app.config import DEFAULT_SENSOR_STATUS, MIN_SENSOR_INTERVAL_SECONDS
from app.definitions.sensors.base import LaunchingSensor, run_key
from app.definitions.sensors.git.base import GitAPIFactory, GitSensor
from app.models import PullRequestResult, PullRequestResultStep, ResultsRepository, ResultState

# PUSHED may have a pull request its result missed, OPENED may be merged or closed since.
SYNCED = [PullRequestResultStep.PUSHED, PullRequestResultStep.OPENED]


def get_synced_results(backend_api: BackendAPI) -> list[PullRequestResult]:
    """The results to sync, of every project: the backend filters them by step."""
    return [
        result
        for project in backend_api.get_projects()
        for result in backend_api.get_results_by_step(project.id, [step.value for step in SYNCED])
    ]


@dg.op(
    config_schema={"project_id": dg.Field(int), "result_id": dg.Field(int), "patch": dg.Field(dict)},
    required_resource_keys={"backend_api"},
)
def sync_results_pull_requests(context: OpExecCtx):
    """
    Record on one result what the sensor found of its pull request: the patch in the run config,
    the step MERGED, CLOSED or OPENED, and for a PUSHED result its number, url and the state
    DELIVERED. A 409 from the backend (the result moved on already) is logged and skipped.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    config = context.op_config
    try:
        backend_api.patch_result(config["project_id"], config["result_id"], config["patch"])
    except requests.HTTPError as e:
        if e.response.status_code != HTTPStatus.CONFLICT:
            raise
        # The result moved on already and keeps its step
        context.log.warning(f"Result {config['result_id']} not moved to {config['patch']['step']}: {e.response.text}")


@dg.job
def sync_results_pull_requests_job():
    """
    Record the step of one result's pull request (run config: project_id, result_id, patch).
    Its tags are trigger=results-pr-sync and result_id, never trigger=task: the run-status sensors act on that.
    """
    sync_results_pull_requests()  # pylint: disable=no-value-for-parameter  # Dagster injects context


class ResultsPullRequestSyncSensor(LaunchingSensor, GitSensor):
    """
    Reads the git provider for every PUSHED or OPENED result, with its ResultsRepository's secret,
    and launches sync_results_pull_requests_job for each result whose pull request differs from
    what it records:
    - PUSHED: the pull request of the result's branch exists.
    - OPENED: the pull request is MERGED or CLOSED now.
    A result with no change has no run. The run key names the result and the step it moves to, see
    run_key: a change launches at once, and a failed run is retried once per retry interval. A result
    with a run still queued or started is skipped, and the provider is not read for it.
    A result whose project resource or pull request is deleted (404) is logged and skipped. A failed
    check is logged and the other results still launch, see LaunchingSensor.
    """

    job = sync_results_pull_requests_job
    failure_label = "Results pull request sync"
    skip_message = "No results pull request changed."

    def __init__(self, context, backend_api: BackendAPI, git_apis: GitAPIFactory):
        super().__init__(context, backend_api, git_apis)
        self.repositories: dict[int, ResultsRepository | None] = {}
        self.patches: dict[int, dict] = {}

    def items(self) -> list[PullRequestResult]:
        return get_synced_results(self.backend_api)

    def describe(self, item: PullRequestResult) -> str:
        return f"Results pull request of result {item.id}"

    def tags(self, item: PullRequestResult) -> dict[str, str]:
        return {"trigger": "results-pr-sync", "result_id": str(item.id)}

    def repository(self, item: PullRequestResult) -> ResultsRepository | None:
        """The repository the result was delivered to, which may not be the project's current one. None if deleted."""
        if item.results_repository_id not in self.repositories:
            try:
                self.repositories[item.results_repository_id] = self.backend_api.get_results_repository_by_id(
                    item.project_id, item.results_repository_id
                ).results_repository
            except requests.HTTPError as e:
                if e.response.status_code != HTTPStatus.NOT_FOUND:
                    raise
                self.repositories[item.results_repository_id] = None
        return self.repositories[item.results_repository_id]

    def ready(self, item: PullRequestResult) -> bool:
        """Whether the provider's pull request differs from the result, noting the patch that records it."""
        repository = self.repository(item)
        if repository is None:
            self.log.warning(f"The project resource of result {item.id} is deleted, skipped")
            return False
        git_api = self.git_apis.for_repository(repository)
        if item.step == PullRequestResultStep.PUSHED:
            base_branch = git_api.get_default_branch(repository.repo_path)
            pr = git_api.find_pull_request_by_branch(repository.repo_path, item.branch, base_branch)
            if pr is None:
                return False
            found = {"number": pr["number"], "url": pr["html_url"], "state": ResultState.DELIVERED.value}
        else:
            try:
                pr = git_api.get_pull_request(repository.repo_path, item.number)
            except requests.HTTPError as e:
                if e.response.status_code != HTTPStatus.NOT_FOUND:
                    raise
                self.log.warning(f"Results pull request {item.url} is not found, skipped")
                return False
            found = {}
        step = PullRequestResultStep.from_git(pr)
        if not found and step == item.step:
            return False
        self.log.info(f"Results pull request {pr['html_url']} is {step.value}")
        self.patches[item.id] = {
            **found,
            "step": step.value,
            "merged_at": pr["merged_at"],
            # GitHub fills merge_commit_sha on an unmerged PR with its test merge
            "merge_commit_sha": pr["merge_commit_sha"] if step == PullRequestResultStep.MERGED else None,
        }
        return True

    def run_request(self, item: PullRequestResult) -> dg.RunRequest:
        """The run that records the pull request's step on the result."""
        patch = self.patches[item.id]
        return dg.RunRequest(
            run_key=run_key("sync-result", item.id, patch["step"]),
            tags=self.tags(item),
            run_config={"ops": {sync_results_pull_requests.name: {"config": {
                "project_id": item.project_id, "result_id": item.id, "patch": patch
            }}}},
        )


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=DEFAULT_SENSOR_STATUS,
    required_resource_keys={"backend_api", "git_apis"},
    job=sync_results_pull_requests_job,
)
def results_pull_request_sync_sensor(context: SensorEvaluationContext):
    """
    Launch sync_results_pull_requests_job for each PUSHED or OPENED result whose pull request
    changed on the provider, unless a run for it is in flight, see ResultsPullRequestSyncSensor.
    """
    sensor = ResultsPullRequestSyncSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        git_apis=cast(GitAPIFactory, context.resources.git_apis),
    )
    yield from sensor()
