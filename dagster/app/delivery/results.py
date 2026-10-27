"""
Delivery of one task's results to its project's results repository.

task_results_delivery_sensor launches a delivery once per task attempt. A failed delivery is
relaunched by results_delivery_retry_sensor up to DAGSTER_DELIVERY_MAX_ATTEMPTS attempts, then by
hand, and resumes from where it stopped.
results_pull_request_sync_sensor only heals a pull request opened but not recorded.
"""

import json
import tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path

import requests

from app.backend import BackendAPI
from app.config import ResultsDeliveryConfig
from app.delivery import git_push
from app.models import (
    PullRequestResultStep, ResultsRepository, ResultState, Task, TaskTrigger, TriggerRepositoryRef,
)
from app.secrets import read_secret_value

ZIP_NAME = "results.zip"
METADATA_NAME = "metadata.json"
SPEC_NAME = "spec.json"
MAX_ERROR_LENGTH = 1000
REVOKED_ERROR = "results repository access revoked"
SWITCHED_OFF_ERROR = "results resource switched off"
# Past these the pull request is opened, so there is nothing left to deliver.
PAST_PUSHED = {PullRequestResultStep.OPENED, PullRequestResultStep.MERGED, PullRequestResultStep.CLOSED}
# REVOKED and STALE are final too, but nothing was delivered.
FINAL = PAST_PUSHED | {PullRequestResultStep.REVOKED, PullRequestResultStep.STALE}


class ResultsDelivery:
    """
    Zips a task's artifacts and pushes them with the task's spec and a metadata file to a new branch of
    the project's results repository, opens a pull request from it into the repository's default
    branch, and records each step on the task's result as soon as it is done.
    Delivery never touches the task's own status.
    """

    def __init__(self, backend_api: BackendAPI, git_apis, config: ResultsDeliveryConfig, log):
        self.backend_api = backend_api
        self.git_apis = git_apis
        self.config = config
        self.log = log

    def __call__(self, project_id: int, task_id: int, run_id: str) -> None:
        """
        Deliver the results of a task run, whose artifacts are in a folder named after run_id,
        which the sensor read from the finished run: record the step PUSHED once the branch is
        pushed, then OPENED and the state DELIVERED once its pull request is opened. A result
        past PUSHED is left alone, and one in UNKNOWN or PUSHED resumes, a FAILED one back to
        IN_PROGRESS: a branch already on the remote is not pushed again, and its pull request
        is looked up before one is opened.
        Where to deliver (the results repository's id and the target_dir) comes from the task's pinned
        configuration, not from the project's results resource, which may be deleted by now. The backend's
        POST /results is the only gate: no result is created when it refuses with a 409 (the task is not
        SUCCESS) and a 404 (the project, task or results repository is gone) is final: both are logged and
        skipped, never raised, so nothing retries them.
        A result the backend created at the final step STALE (the task's configuration changed since the task
        was created) is left alone, with a warning.
        A revoked or deleted project resource gives a result at the final step REVOKED, nothing is delivered and nothing is raised.
        A project resource that is not active for another reason fails the result with an error and
        raises nothing: its error is "results resource switched off", and the retry sensor delivers it once the resource is active again.
        Any failure is recorded on the result as an error with one more attempt, its step
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
        if result.step in PAST_PUSHED:
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

        pushed = {}
        try:
            pull_request = self._find_pull_request(task)
            title = f"{pull_request.trigger_repository.repo_path} PR{pull_request.number} - task {task.id} - results"
            branch, commit_sha, base_branch = self._push(task, run_id, repository, results["target_dir"], pull_request.trigger_repository, pull_request, title)
            pushed = {"branch": branch, "commit_sha": commit_sha}
            self.backend_api.patch_result(task.project_id, result.id, {"step": PullRequestResultStep.PUSHED.value, **pushed})
            results_pr = self._open_pull_request(repository, branch, base_branch, title, pull_request)
            # An earlier attempt's PR may be merged or closed already: record what it is
            step = PullRequestResultStep.from_git(results_pr)
            self.backend_api.patch_result(task.project_id, result.id, {
                "step": step.value,
                "state": ResultState.DELIVERED.value,
                "attempts": result.attempts + 1,
                "error": None,
                "number": results_pr["number"],
                "url": results_pr["html_url"],
                "merged_at": results_pr["merged_at"],
                # GitHub fills merge_commit_sha on an unmerged PR with its test merge
                "merge_commit_sha": results_pr["merge_commit_sha"] if step == PullRequestResultStep.MERGED else None,
            })
        except Exception as e:
            self.backend_api.patch_result(task.project_id, result.id, {
                "state": ResultState.FAILED.value,
                "attempts": result.attempts + 1,
                "error": f"{type(e).__name__}: {e}"[:MAX_ERROR_LENGTH],
                **pushed,
            })
            raise
        self.log.info(f"Delivered results of task {task.id} in {results_pr['html_url']}")

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
        target_dir: str,
        trigger_repository: TriggerRepositoryRef,
        pull_request: TaskTrigger,
        message: str,
    ) -> tuple[str, str, str]:
        """
        Push the results to their branch and return the branch, its commit sha and the
        repository's default branch. The branch name is fixed by the layout and the merge sha,
        so a branch already on the remote is from an earlier attempt and is not pushed again.
        """
        # TODO(auth): the token read and the Keycloak system user are being reworked
        env = git_push.auth_env(read_secret_value(repository.secret, "TOKEN"))

        layout = Path(target_dir.strip("/")) / self._name(trigger_repository) / str(
            pull_request.number
        ) / str(task.id)
        branch = f"{layout.as_posix()}-{pull_request.merge_commit_sha[:7]}"

        with tempfile.TemporaryDirectory(prefix="phems-results-") as work:
            clone_dir = Path(work) / "repo"
            git_push.clone(
                git_push.clone_url(repository.provider.uri, repository.repo_path),
                clone_dir, env,
            )
            base_branch = git_push.current_branch(clone_dir)
            commit_sha = git_push.remote_branch_sha(clone_dir, branch, env)
            if commit_sha:
                self.log.info(f"Branch {branch} is already pushed at {commit_sha}")
                return branch, commit_sha, base_branch

            artifacts = Path(self.config.artifact_mount_path) / run_id
            if artifacts.is_symlink() or not artifacts.is_dir():
                raise FileNotFoundError(f"No artifacts at {artifacts}")

            zip_path = Path(work) / ZIP_NAME
            git_push.zip_dir(artifacts, zip_path)
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
            (out_dir / SPEC_NAME).write_text(json.dumps(task.spec.model_dump(), indent=2) + "\n")
            (out_dir / METADATA_NAME).write_text(json.dumps({
                "branch": branch,
                "merge_commit_sha": pull_request.merge_commit_sha,
                "task_id": task.id,
                "executor_run_id": run_id,
                "trigger_repository_uri": trigger_repository.uri,
                "number": pull_request.number,
                "delivered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "zip_size_bytes": zip_size,
            }, indent=2) + "\n")

            return branch, git_push.commit_and_push(clone_dir, message, env), base_branch

    def _open_pull_request(
        self, repository: ResultsRepository, branch: str, base_branch: str, title: str, pull_request: TaskTrigger
    ) -> dict:
        """Open the pull request of the branch, or return the one an earlier attempt opened."""
        git_api = self.git_apis.for_repository(repository)
        existing = git_api.find_pull_request_by_branch(repository.repo_path, branch, base_branch)
        if existing:
            self.log.info(f"Branch {branch} already has pull request #{existing['number']}")
            return existing
        body = (
            f"Results of the task run for pull request #{pull_request.number}, "
            f"merged at {pull_request.merge_commit_sha}."
        )
        return git_api.create_pull_request(repository.repo_path, branch, base_branch, title, body)

    def _find_pull_request(self, task: Task) -> TaskTrigger:
        """The pull request that yielded the task, with its trigger repository. A task without one is a 404."""
        return self.backend_api.get_task_trigger(task.project_id, task.id)

    @staticmethod
    def _name(repository: TriggerRepositoryRef) -> str:
        """The trigger repository's name: the last segment of its path."""
        return repository.repo_path.split("/")[-1]
