"""
Opens the results pull requests and tracks them against the git provider. Delivery stops at the
push, with the result PUSHED and DELIVERED: this sensor opens the pull request of each pushed
result and moves the result to OPENED, MERGED or CLOSED as the pull request does. It reads the
provider once per results repository per tick, whatever the number of results. A node that wants
push-only delivery stops this sensor. A failed delivery is not retried here, see app.delivery.results.
"""
from http import HTTPStatus
from typing import cast

import requests
import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, SensorEvaluationContext

from app.backend import BackendAPI
from app.config import DEFAULT_SENSOR_STATUS, DELIVERY_MAX_ATTEMPTS, MIN_SENSOR_INTERVAL_SECONDS
from app.definitions.sensors.base import LaunchingSensor, run_in_flight, run_key
from app.definitions.sensors.git.base import GitAPI, GitAPIFactory, GitSensor
from app.delivery.results import MAX_ERROR_LENGTH, results_title
from app.models import PullRequestResult, PullRequestResultStep, ResultsRepository


def get_synced_results(backend_api: BackendAPI) -> list[PullRequestResult]:
    """
    The results to sync, of every project, with attempts left: the PUSHED ones, and the OPENED ones, which
    may be merged or closed since.
    """
    return [
        result
        for project in backend_api.get_projects()
        for result in (
            *backend_api.get_results_by_step(project.id, [PullRequestResultStep.PUSHED.value]),
            *backend_api.get_results_by_step(project.id, [PullRequestResultStep.OPENED.value]),
        )
        if result.attempts < DELIVERY_MAX_ATTEMPTS
    ]


def record(pr: dict) -> dict:
    """What a result records of its results pull request, from the git provider's response."""
    step = PullRequestResultStep.from_git(pr)
    return {
        "step": step.value,
        "number": pr["number"],
        "url": pr["html_url"],
        "merged_at": pr["merged_at"],
        # GitHub fills merge_commit_sha on an unmerged PR with its test merge
        "merge_commit_sha": pr["merge_commit_sha"] if step == PullRequestResultStep.MERGED else None,
    }


@dg.op(
    config_schema={"project_id": dg.Field(int), "result_id": dg.Field(int), "patch": dg.Field(dict)},
    required_resource_keys={"backend_api"},
)
def sync_results_pull_requests(context: OpExecCtx):
    """
    Record on one result what the sensor found of its pull request: the patch in the run config,
    its step (OPENED, MERGED or CLOSED), number and url. A 409 from the backend (the result moved on
    already) is logged and skipped.
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


@dg.op(
    config_schema={
        "project_id": dg.Field(int), "result_id": dg.Field(int), "task_id": dg.Field(int),
        "results_repository_id": dg.Field(int), "branch": dg.Field(str), "base_branch": dg.Field(str),
        "attempts": dg.Field(int),
    },
    required_resource_keys={"backend_api", "git_apis"},
)
def open_results_pull_request(context: OpExecCtx):
    """
    Open the pull request from a pushed result's branch into the task's pinned base_branch, and record
    it on the result: its step, number and url, with the attempts and error of earlier failures cleared.
    A failure is recorded as an error with one more attempt, the state left DELIVERED so the delivery
    retry sensor, which takes FAILED only, leaves the result alone, and raised so the run fails visibly.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    config = context.op_config
    try:
        repository = backend_api.get_global_results_repository(config["results_repository_id"])
        pull_request = backend_api.get_task_trigger(config["project_id"], config["task_id"])
        git_api = cast(GitAPIFactory, context.resources.git_apis).for_repository(repository, config["project_id"])
        body = (
            f"Results of the task run for pull request #{pull_request.number}, "
            f"merged at {pull_request.merge_commit_sha}."
        )
        pr = git_api.create_pull_request(
            repository.repo_path, config["branch"], config["base_branch"], results_title(pull_request, config["task_id"]), body
        )
        backend_api.patch_result(config["project_id"], config["result_id"], {**record(pr), "attempts": 0, "error": None})
    except Exception as e:
        backend_api.patch_result(config["project_id"], config["result_id"], {
            "attempts": config["attempts"] + 1,
            "error": f"{type(e).__name__}: {e}"[:MAX_ERROR_LENGTH],
        })
        raise
    context.log.info(f"Opened results pull request {pr['html_url']} for task {config['task_id']}")


@dg.job
def open_results_pull_request_job():
    """
    Open the results pull request of one pushed result (run config: project_id, result_id, task_id,
    results_repository_id, branch, base_branch, attempts). Its tags are trigger=results-pr-sync and
    result_id, as the sync job's, never trigger=task: the run-status sensors act on that.
    """
    open_results_pull_request()  # pylint: disable=no-value-for-parameter  # Dagster injects context


class ResultsPullRequestSyncSensor(LaunchingSensor, GitSensor):
    """
    Reads the git provider's pull requests of each results repository, with its secret, and launches a run
    for each PUSHED or OPENED result with attempts left:
    - PUSHED: the pull request of the result's branch into the task's pinned base_branch exists, and
      sync_results_pull_requests_job records it; or it does not, and open_results_pull_request_job opens it.
    - OPENED: the pull request is MERGED or CLOSED now, and sync_results_pull_requests_job records it.
    A result with no change has no run. The provider is listed once per results repository per tick, the
    pull requests updated since the repository's oldest result, whatever the number of results. The run
    key names the result and the step it moves to, see run_key: a change launches at once, and a failed
    run is retried once per retry interval, until the result's attempts run out. A result with a run of
    either job still queued or started is skipped.
    A result whose project resource is deleted is logged and skipped. A failed check is logged and the
    other results still launch, see LaunchingSensor.
    """

    job = sync_results_pull_requests_job
    open_job = open_results_pull_request_job
    failure_label = "Results pull request sync"
    skip_message = "No results pull request to open or sync."

    def __init__(self, context, backend_api: BackendAPI, git_apis: GitAPIFactory):
        super().__init__(context, backend_api, git_apis)
        self.repositories: dict[int, ResultsRepository | None] = {}
        self.clients: dict[int, GitAPI] = {}
        self.since: dict[int, str] = {}
        self.pulls: dict[int, list[dict]] = {}
        self.patches: dict[int, dict] = {}
        self.base_branches: dict[int, str] = {}

    def items(self) -> list[PullRequestResult]:
        results = get_synced_results(self.backend_api)
        for result in results:
            # A pull request is created after its result, so none of its results' pull requests is older
            self.since[result.results_repository_id] = min(
                result.created_at, self.since.get(result.results_repository_id, result.created_at)
            )
        return results

    def describe(self, item: PullRequestResult) -> str:
        return f"Results pull request of result {item.id}"

    def tags(self, item: PullRequestResult) -> dict[str, str]:
        return {"trigger": "results-pr-sync", "result_id": str(item.id)}

    def in_flight(self, item: PullRequestResult) -> bool:
        return any(run_in_flight(self.context, job, self.tags(item)) for job in (self.job, self.open_job))

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

    def pull_requests(self, item: PullRequestResult, repository: ResultsRepository) -> list[dict]:
        """
        The pull requests of the item's results repository, updated since its oldest result. One call, with
        one token, per repository per tick, whatever the number of its results.
        """
        repository_id = item.results_repository_id
        if repository_id not in self.pulls:
            if repository_id not in self.clients:
                self.clients[repository_id] = self.git_apis.for_repository(repository)
            # The backend's datetimes are UTC, as "2026-10-08 10:00:00"
            since = self.since[repository_id].replace(" ", "T") + "Z"
            self.pulls[repository_id] = self.clients[repository_id].get_pulls(repository.repo_path, since=since, state="all")
        return self.pulls[repository_id]

    def ready(self, item: PullRequestResult) -> bool:
        """Whether the result needs a run: noting the patch that records its pull request, or the base branch to open it into."""
        repository = self.repository(item)
        if repository is None:
            self.log.warning(f"The project resource of result {item.id} is deleted, skipped")
            return False
        pulls = self.pull_requests(item, repository)
        if item.step == PullRequestResultStep.PUSHED:
            # The base branch the delivery used: the task's pinned one, the assignment may have changed since
            results = self.backend_api.get_task_config(item.project_id, item.task_id)["config_snapshot"]["results"]
            base_branch = results["base_branch"]
            pr = next((p for p in pulls if p["head"]["ref"] == item.branch and p["base"]["ref"] == base_branch), None)
            if pr is None:
                self.base_branches[item.id] = base_branch
                return True
            # What a failed opening left of the attempts and error is cleared
            patch = {**record(pr), "attempts": 0, "error": None}
        else:
            pr = next((p for p in pulls if p["number"] == item.number), None)
            if pr is None:
                self.log.warning(f"Results pull request {item.url} is not listed, skipped")
                return False
            patch = record(pr)
            if patch["step"] == item.step.value:
                return False
        self.log.info(f"Results pull request {pr['html_url']} is {patch['step']}")
        self.patches[item.id] = patch
        return True

    def run_request(self, item: PullRequestResult) -> dg.RunRequest:
        """The run that opens the result's pull request, or records the pull request's step on the result."""
        if item.id in self.base_branches:
            return dg.RunRequest(
                run_key=run_key("open-result", item.id, PullRequestResultStep.OPENED.value),
                job_name=self.open_job.name,
                tags=self.tags(item),
                run_config={"ops": {open_results_pull_request.name: {"config": {
                    "project_id": item.project_id, "result_id": item.id, "task_id": item.task_id,
                    "results_repository_id": item.results_repository_id, "branch": item.branch,
                    "base_branch": self.base_branches[item.id], "attempts": item.attempts,
                }}}},
            )
        patch = self.patches[item.id]
        return dg.RunRequest(
            run_key=run_key("sync-result", item.id, patch["step"]),
            job_name=self.job.name,
            tags=self.tags(item),
            run_config={"ops": {sync_results_pull_requests.name: {"config": {
                "project_id": item.project_id, "result_id": item.id, "patch": patch
            }}}},
        )


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=DEFAULT_SENSOR_STATUS,
    required_resource_keys={"backend_api", "git_apis"},
    jobs=[sync_results_pull_requests_job, open_results_pull_request_job],
)
def results_pull_request_sync_sensor(context: SensorEvaluationContext):
    """
    Launch open_results_pull_request_job for each PUSHED result without a pull request, and
    sync_results_pull_requests_job for each PUSHED or OPENED result whose pull request changed on
    the provider, unless a run for it is in flight, see ResultsPullRequestSyncSensor.
    """
    sensor = ResultsPullRequestSyncSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
        git_apis=cast(GitAPIFactory, context.resources.git_apis),
    )
    yield from sensor()
