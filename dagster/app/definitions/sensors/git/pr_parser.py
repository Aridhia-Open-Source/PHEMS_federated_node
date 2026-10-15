from enum import Enum

from pydantic import BaseModel

from app.definitions.sensors.git.base import GitAPI
from app.models import PullRequestTrigger, TriggerRepository


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
    # The spec file as read, for the backend to parse
    spec_raw: str | None = None
    # Why the PR is IGNORED or REJECTED
    state_cause: str | None = None


def is_under_dir(filename: str, directory: str) -> bool:
    """
    Whether the file's directory is the given directory or inside it, matching whole path
    segments. An empty directory is the whole repository.
    """
    wanted = [s for s in directory.split("/") if s not in ("", ".")]
    return filename.split("/")[:-1][:len(wanted)] == wanted


class PullRequestParser:
    """
    Reads the spec a pull request carries: finds the new spec file in the repository's
    watch_dir and reads it at the merge commit. The backend parses and validates the spec.
    """

    def __init__(self, git_api: GitAPI, repo: TriggerRepository, log):
        self.git_api = git_api
        self.repo = repo
        self.log = log

    def parse(self, pr: PullRequestTrigger) -> ParsedPullRequest:
        """
        IGNORED if the PR has no watched file, REJECTED if it has several, else READY with
        the spec file's contents. A git provider failure raises: it is not an outcome.
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
        return ParsedPullRequest(outcome=PullRequestOutcome.READY, spec_raw=contents)

    def _filter_watched_files(self, pr_files: list[dict]):
        def _is_watched_json_file(f):
            is_dir = is_under_dir(f["filename"], self.repo.watch_dir)
            is_ext = f["filename"].endswith('.json')
            is_new = f["status"] == "added"
            return is_dir and is_ext and is_new

        return [f for f in pr_files if _is_watched_json_file(f)]
