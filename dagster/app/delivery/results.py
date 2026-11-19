"""
Delivery of one task's results to its project's results repository.

task_results_delivery_sensor launches a delivery once per task attempt. A failed delivery is
relaunched by results_delivery_retry_sensor up to DAGSTER_DELIVERY_MAX_ATTEMPTS attempts, then by
hand, and resumes from where it stopped.
Delivery stops at the push: the results are DELIVERED once the branch is pushed.
results_pull_request_sync_sensor opens the pull request and tracks it to MERGED or CLOSED.
"""

import tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path

import requests

from app.backend import BackendAPI
from app.config import ResultsDeliveryConfig
from app.delivery import git_push
from app.models import (
    PullRequestResultStep, ResultsRepository, ResultState, RunNode, RunProject, RunRecord, RunResults, RunTask,
    RunTrigger, Task, TaskTrigger, TriggerRepositoryRef,
)

ZIP_NAME = "results.zip"
RUN_NAME = "run.json"
SPEC_NAME = "spec.json"
MAX_ERROR_LENGTH = 1000
REVOKED_ERROR = "results repository access revoked"
SWITCHED_OFF_ERROR = "results resource switched off"
# From PUSHED on the branch is on the remote, so there is nothing left to deliver.
PUSHED_OR_BEYOND = {
    PullRequestResultStep.PUSHED, PullRequestResultStep.OPENED, PullRequestResultStep.MERGED, PullRequestResultStep.CLOSED,
}
# REVOKED and STALE are final too, but nothing was delivered.
FINAL = PUSHED_OR_BEYOND | {PullRequestResultStep.REVOKED, PullRequestResultStep.STALE}


def results_title(pull_request: TaskTrigger, task_id: int) -> str:
    """The commit message of a task's results and the title of their pull request."""
    return f"{pull_request.trigger_repository.repo_path} PR{pull_request.number} - task {task_id} - results"


class ResultsDelivery:
    """
    Zips a task's artifacts and pushes them with the pull request's spec file and a run.json to a new
    branch of the project's results repository, and records the step PUSHED and the state DELIVERED on
    the task's result. It opens no pull request: results_pull_request_sync_sensor does.
    Delivery never touches the task's own status.
    """

    def __init__(self, backend_api: BackendAPI, config: ResultsDeliveryConfig, log):
        self.backend_api = backend_api
        self.config = config
        self.log = log

    def __call__(self, project_id: int, task_id: int, run_id: str) -> None:
        """
        Deliver the results of a task run, whose artifacts are in a folder named after run_id,
        which the sensor read from the finished run: record the step PUSHED and the state DELIVERED
        once the branch is pushed, with its attempts and error reset for the pull request's opening.
        A result at PUSHED or beyond is left alone, and one in UNKNOWN resumes, a FAILED one back to
        IN_PROGRESS: a branch already on the remote is not pushed again.
        Where to deliver (the results repository's id, its base_branch and the target_dir) comes from the task's pinned
        configuration, not from the project's results resource, which may be deleted by now. The backend's
        POST /results is the only gate: no result is created when it refuses with a 409 (the task is not
        SUCCESS) and a 404 (the project, task or results repository is gone) is final: both are logged and
        skipped, never raised, so nothing retries them.
        A result the backend created at the final step STALE (the task's configuration changed since the task
        was created) is left alone, with a warning.
        A revoked or deleted project resource gives a result at the final step REVOKED, nothing is delivered and nothing is raised.
        A project resource that is not active for another reason fails the result with an error and
        raises nothing: its error is "results resource switched off", and the retry sensor delivers it once the resource is active again.
        A failed push is recorded on the result as an error with one more attempt, its step
        left where it was and its state FAILED, and raised, so the Dagster run fails visibly.
        """
        try:
            task = self.backend_api.get_task(project_id, task_id)
            # Where to deliver is what the task was created under: its project resource may be deleted by now
            results = self.backend_api.get_task_config(task.project_id, task.id)["config_snapshot"]["results"]
            result = self.backend_api.create_result(task.project_id, task.id, results["repository_id"])
        except requests.HTTPError as e:
            self._stop_if_refused(task_id, e)
            return
        if result.step == PullRequestResultStep.REVOKED:
            self.log.warning(f"Results of task {task.id} not delivered: {REVOKED_ERROR}")
            return
        if result.step == PullRequestResultStep.STALE:
            self.log.warning(f"Results of task {task.id} not delivered: {result.error}")
            return
        if result.step in PUSHED_OR_BEYOND:
            self.log.info(f"Results of task {task.id} are already delivered, {result.step.value}")
            return
        if result.state == ResultState.FAILED and result.error == SWITCHED_OFF_ERROR and result.attempts == 0:
            # Just recorded by the backend, which found the resource switched off. The retry sensor
            # delivers it once the resource is active again, with its attempts at 1 by then.
            self.log.warning(f"Results of task {task.id} not delivered: {SWITCHED_OFF_ERROR}")
            self.backend_api.patch_result(task.project_id, result.id, {"attempts": result.attempts + 1})
            return
        try:
            repository = self.backend_api.get_global_results_repository(results["repository_id"])
        except requests.HTTPError as e:
            self._stop_if_refused(task_id, e)
            return
        if result.state == ResultState.FAILED:
            self.backend_api.patch_result(task.project_id, result.id, {"state": ResultState.IN_PROGRESS.value})

        try:
            pull_request = self._find_pull_request(task)
            branch, commit_sha = self._push(
                task, run_id, repository, results["base_branch"], results["target_dir"], pull_request.trigger_repository,
                pull_request, results_title(pull_request, task.id),
            )
            # The pull request's opening starts from no attempts and no error
            self.backend_api.patch_result(task.project_id, result.id, {
                "step": PullRequestResultStep.PUSHED.value,
                "state": ResultState.DELIVERED.value,
                "attempts": 0,
                "error": None,
                "branch": branch,
                "commit_sha": commit_sha,
            })
        except Exception as e:
            self.backend_api.patch_result(task.project_id, result.id, {
                "state": ResultState.FAILED.value,
                "attempts": result.attempts + 1,
                "error": f"{type(e).__name__}: {e}"[:MAX_ERROR_LENGTH],
            })
            raise
        self.log.info(f"Delivered results of task {task.id} to branch {branch}")

    def _stop_if_refused(self, task_id: int, error: requests.HTTPError) -> None:
        """
        Logs a 404 (the project, task or repository is gone: the result is final, nothing to retry) or a 409
        (the task is not SUCCESS) and lets the caller stop. Any other error is raised.
        """
        if error.response.status_code not in (HTTPStatus.NOT_FOUND, HTTPStatus.CONFLICT):
            raise error
        self.log.warning(f"Results of task {task_id} not delivered: {error.response.text}")

    def _push(
        self,
        task: Task,
        run_id: str,
        repository: ResultsRepository,
        base_branch: str,
        target_dir: str,
        trigger_repository: TriggerRepositoryRef,
        pull_request: TaskTrigger,
        message: str,
    ) -> tuple[str, str]:
        """
        Push the results to a new branch of base_branch and return the branch and its commit sha.
        The branch name is fixed by the layout and the merge sha, so a branch already on the remote
        is from an earlier attempt and is not pushed again.
        """
        # Asked for here, just before the git commands that need it: it lasts an hour
        env = git_push.auth_env(self.backend_api.get_repository_token("results", repository.id, task.project_id).token)

        layout = Path(target_dir.strip("/")) / self._name(trigger_repository) / str(
            pull_request.number
        ) / str(task.id)
        branch = f"{layout.as_posix()}-{pull_request.merge_commit_sha[:7]}"

        with tempfile.TemporaryDirectory(prefix="phems-results-") as work:
            clone_dir = Path(work) / "repo"
            git_push.clone(
                git_push.clone_url(repository.provider.uri, repository.repo_path),
                base_branch, clone_dir, env,
            )
            commit_sha = git_push.remote_branch_sha(clone_dir, branch, env)
            if commit_sha:
                self.log.info(f"Branch {branch} is already pushed at {commit_sha}")
                return branch, commit_sha

            artifacts = Path(self.config.artifact_mount_path) / run_id
            if artifacts.is_symlink() or not artifacts.is_dir():
                raise FileNotFoundError(f"No artifacts at {artifacts}")

            zip_path = Path(work) / ZIP_NAME
            file_count = git_push.zip_dir(artifacts, zip_path)
            zip_size = zip_path.stat().st_size
            if zip_size > self.config.max_zip_bytes:
                raise ValueError(
                    f"{ZIP_NAME} is {zip_size} bytes, over the {self.config.max_zip_bytes} byte limit"
                )

            out_dir = clone_dir / layout
            # target_dir is checked at the API, and a link inside the results repository could still lead out
            if not out_dir.resolve().is_relative_to(clone_dir.resolve()):
                raise ValueError(f"Output path {layout} is outside the clone")
            git_push.checkout_new_branch(clone_dir, branch)
            out_dir.mkdir(parents=True, exist_ok=True)
            zip_path.replace(out_dir / ZIP_NAME)
            # The spec file as it was merged, not re-serialised
            (out_dir / SPEC_NAME).write_bytes(pull_request.spec_raw.encode())
            run = RunRecord(
                node=RunNode(id=self.config.node_id),
                project=RunProject(id=task.project_id, name=task.project_name),
                trigger=RunTrigger(
                    repository_uri=trigger_repository.uri,
                    pr_number=pull_request.number,
                    merge_commit_sha=pull_request.merge_commit_sha,
                ),
                task=RunTask(id=task.id, name=task.name, executor_id=run_id, dataset=task.dataset_name),
                results=RunResults(
                    zip_size_bytes=zip_size,
                    file_count=file_count,
                    delivered_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                ),
            )
            (out_dir / RUN_NAME).write_text(run.model_dump_json(indent=2) + "\n")

            return branch, git_push.commit_and_push(clone_dir, message, env)

    def _find_pull_request(self, task: Task) -> TaskTrigger:
        """The pull request that yielded the task, with its trigger repository. A task without one is a 404."""
        return self.backend_api.get_task_trigger(task.project_id, task.id)

    @staticmethod
    def _name(repository: TriggerRepositoryRef) -> str:
        """The trigger repository's name: the last segment of its path."""
        return repository.repo_path.split("/")[-1]
