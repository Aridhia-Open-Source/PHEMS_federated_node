"""Delivery of one task's results to its project's results repository."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.backend import BackendAPI
from app.config import ResultsDeliveryConfig
from app.delivery import git_push
from app.models import (
    PullRequest, MergeStatus, ResultsRepository, Task, TaskResultStatus, TriggerRepository, TriggerState,
)
from app.secrets import SecretProvider

ZIP_NAME = "results.zip"
METADATA_NAME = "metadata.json"
SPEC_NAME = "spec.json"
MAX_ERROR_LENGTH = 1000


class ResultsDelivery:
    """
    Zips a task's artifacts and pushes them with the task's spec and a metadata file to a new branch of
    the project's results repository, opens a pull request from it into the repository's default
    branch, then records the outcome on the task's TaskResult.
    Delivery never touches the task's own status.
    """

    def __init__(self, backend_api: BackendAPI, git_apis, config: ResultsDeliveryConfig, log):
        self.backend_api = backend_api
        self.git_apis = git_apis
        self.config = config
        self.log = log

    def __call__(self, task_id: int) -> None:
        """
        Deliver the results of a task. A delivered one is left alone. Any failure is
        recorded on the TaskResult as FAILED and raised, so the Dagster run fails visibly.
        A pushed branch is recorded even when its pull request fails, and a retry reuses it.
        """
        task = self.backend_api.get_task(task_id)
        repository = self.backend_api.get_results_repository(task.project_id)
        task_result = self.backend_api.create_task_result(task.id, repository.id)
        if task_result.status == TaskResultStatus.DELIVERED:
            self.log.info(f"Results of task {task.id} are already delivered")
            return

        pushed = {}
        try:
            trigger_repository, pull_request = self._find_pull_request(task)
            title = f"{trigger_repository.repo_path} PR{pull_request.number} - task {task.id} - results"
            branch, commit_sha, base_branch = self._push(task, repository, trigger_repository, pull_request, title)
            pushed = {"branch": branch, "commit_sha": commit_sha}
            results_pr = self._open_pull_request(repository, branch, base_branch, title, pull_request)
        except Exception as e:
            self.backend_api.patch_task_result(task_result.id, {
                "status": TaskResultStatus.FAILED.value,
                "attempts": task_result.attempts + 1,
                "error": f"{type(e).__name__}: {e}"[:MAX_ERROR_LENGTH],
                **pushed,
            })
            raise

        # An earlier attempt's PR may be merged already, and the sync sensor only polls OPEN ones
        state = MergeStatus.from_git(results_pr)
        self.backend_api.patch_task_result(task_result.id, {
            "status": TaskResultStatus.DELIVERED.value,
            "attempts": task_result.attempts + 1,
            "error": None,
            **pushed,
            "number": results_pr["number"],
            "url": results_pr["html_url"],
            "merge_status": state.value,
            "merged_at": results_pr["merged_at"],
            # GitHub fills merge_commit_sha on an unmerged PR with its test merge
            "merge_commit_sha": results_pr["merge_commit_sha"] if state == MergeStatus.MERGED else None,
        })
        self.log.info(f"Delivered results of task {task.id} in {results_pr['html_url']}")

    def _push(
        self,
        task: Task,
        repository: ResultsRepository,
        trigger_repository: TriggerRepository,
        pull_request: PullRequest,
        message: str,
    ) -> tuple[str, str, str]:
        """
        Push the results to their branch and return the branch, its commit sha and the
        repository's default branch. The branch name is fixed by the layout and the merge sha,
        so a branch already on the remote is from an earlier attempt and is not pushed again.
        """
        # TODO(auth): the token read and the Keycloak system user are being reworked
        secret = repository.secret
        token = SecretProvider(secret.provider).get(secret.key, secret.namespace, "TOKEN")
        env = git_push.auth_env(token)

        layout = Path(repository.target_dir.strip("/")) / self._name(trigger_repository) / str(
            pull_request.number
        ) / str(task.id)
        branch = f"{layout.as_posix()}-{pull_request.merge_commit_sha[:7]}"

        with tempfile.TemporaryDirectory(prefix="phems-results-") as work:
            clone_dir = Path(work) / "repo"
            git_push.clone(git_push.clone_url(repository.uri, repository.api_uri), clone_dir, env)
            base_branch = git_push.current_branch(clone_dir)
            commit_sha = git_push.remote_branch_sha(clone_dir, branch, env)
            if commit_sha:
                self.log.info(f"Branch {branch} is already pushed at {commit_sha}")
                return branch, commit_sha, base_branch

            artifacts = Path(self.config.artifact_mount_path) / task.dagster_run_id
            if not artifacts.is_dir():
                raise FileNotFoundError(f"No artifacts at {artifacts}")

            zip_path = Path(work) / ZIP_NAME
            git_push.zip_dir(artifacts, zip_path)
            zip_size = zip_path.stat().st_size
            if zip_size > self.config.max_zip_bytes:
                raise ValueError(
                    f"{ZIP_NAME} is {zip_size} bytes, over the {self.config.max_zip_bytes} byte limit"
                )

            git_push.checkout_new_branch(clone_dir, branch)
            out_dir = clone_dir / layout
            out_dir.mkdir(parents=True, exist_ok=True)
            zip_path.replace(out_dir / ZIP_NAME)
            (out_dir / SPEC_NAME).write_text(json.dumps(task.spec, indent=2) + "\n")
            (out_dir / METADATA_NAME).write_text(json.dumps({
                "branch": branch,
                "merge_commit_sha": pull_request.merge_commit_sha,
                "task_id": task.id,
                "dagster_run_id": task.dagster_run_id,
                "trigger_repository_uri": trigger_repository.uri,
                "number": pull_request.number,
                "delivered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "zip_size_bytes": zip_size,
            }, indent=2) + "\n")

            return branch, git_push.commit_and_push(clone_dir, message, env), base_branch

    def _open_pull_request(
        self, repository: ResultsRepository, branch: str, base_branch: str, title: str, pull_request: PullRequest
    ) -> dict:
        """Open the pull request of the branch, or return the one an earlier attempt opened."""
        git_api = self.git_apis.for_repository(repository)
        existing = git_api.find_pull_request_by_branch(repository.repo_path, branch, base_branch)
        if existing:
            self.log.info(f"Branch {branch} already has pull request #{existing['number']}")
            return existing
        body = f"Results of the task run for pull request #{pull_request.number}, merged at {pull_request.merge_commit_sha}."
        return git_api.create_pull_request(repository.repo_path, branch, base_branch, title, body)

    def _find_pull_request(self, task: Task) -> tuple[TriggerRepository, PullRequest]:
        """The trigger repository and pull request that yielded the task."""
        for repository in self.backend_api.get_repositories():
            if repository.project_id != task.project_id:
                continue
            for pull_request in self.backend_api.get_pull_requests(repository.id, TriggerState.YIELDED.value):
                if pull_request.task_id == task.id:
                    return repository, pull_request
        raise LookupError(f"Task {task.id} has no pull request, so its results have no place in the layout")

    @staticmethod
    def _name(repository: TriggerRepository) -> str:
        """The trigger repository's name: the last segment of its path."""
        return repository.repo_path.split("/")[-1]
