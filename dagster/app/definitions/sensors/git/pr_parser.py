import json
from enum import Enum

from pydantic import BaseModel

from app.definitions.sensors.git.base import GitAPI
from app.models import PullRequestTrigger, PullRequestSpec, TriggerRepository


class PullRequestOutcome(str, Enum):
    """
    What evaluating a pull request found. Never persisted: it maps onto the PR's state
    (READY becomes a task and so YIELDED, IGNORED and REJECTED are stored with the state_cause).
    """

    READY = "READY"
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"


class ParsedPullRequest(BaseModel):
    outcome: PullRequestOutcome
    spec: PullRequestSpec | None = None
    # Why the PR is IGNORED or REJECTED
    state_cause: str | None = None


class PullRequestParser:
    """
    Reads the spec a pull request carries: finds the new spec file in the repository's
    watch_dir, reads it at the merge commit and validates its spec.
    """

    def __init__(self, git_api: GitAPI, repo: TriggerRepository, log):
        self.git_api = git_api
        self.repo = repo
        self.log = log

    def parse(self, pr: PullRequestTrigger) -> ParsedPullRequest:
        """
        IGNORED if the PR has no watched file, REJECTED if it has several or its spec is
        invalid, else READY with the spec. A git provider failure raises: it is not an outcome.
        """
        pr_files = self.git_api.get_pull_request_files(self.repo.repo_path, pr.number)
        watched_files = self._filter_watched_files(pr_files)
        watched_file_names = [f["filename"] for f in watched_files]
        self.log.info(f"PR #{pr.number} in {self.repo.repo_path}: watched files {watched_file_names}")

        if not watched_file_names:
            return ParsedPullRequest(
                outcome=PullRequestOutcome.IGNORED,
                state_cause=f"No new spec file under {self.repo.watch_dir}",
            )
        if len(watched_file_names) > 1:
            return ParsedPullRequest(
                outcome=PullRequestOutcome.REJECTED,
                state_cause=f"Several new spec files under {self.repo.watch_dir}: {', '.join(watched_file_names)}",
            )

        contents = self.git_api.get_file_contents(
            repo_path=self.repo.repo_path,
            file_path=watched_file_names[0],
            ref=pr.merge_commit_sha,
        )
        try:
            spec = PullRequestSpec.model_validate(json.loads(contents)["spec"])
        except (ValueError, KeyError, TypeError) as e:
            # ValueError covers bad JSON and pydantic's ValidationError
            self.log.error(f"PR #{pr.number} spec is invalid: {type(e).__name__}: {e}")
            return ParsedPullRequest(
                outcome=PullRequestOutcome.REJECTED,
                state_cause=f"Invalid spec file {watched_file_names[0]}: {type(e).__name__}: {e}",
            )
        return ParsedPullRequest(outcome=PullRequestOutcome.READY, spec=spec)

    def _filter_watched_files(self, pr_files: list[dict]):
        def _is_watched_json_file(f):
            is_dir = f["filename"].startswith(self.repo.watch_dir)
            is_ext = f["filename"].endswith('.json')
            is_new = f["status"] == "added"
            return is_dir and is_ext and is_new

        return [f for f in pr_files if _is_watched_json_file(f)]
