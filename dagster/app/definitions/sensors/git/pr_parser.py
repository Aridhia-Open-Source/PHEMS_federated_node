from enum import Enum

from pydantic import BaseModel

from app.definitions.sensors.git.base import GitAPI
from app.models import ProjectTriggerRepository, PullRequestTrigger


class PullRequestOutcome(str, Enum):
    """
    What evaluating a pull request found. Never persisted: it maps onto the PR's state
    (READY becomes a task and so YIELDED, REJECTED is stored with the state_cause).
    """

    READY = "READY"
    REJECTED = "REJECTED"


class ParsedPullRequest(BaseModel):
    outcome: PullRequestOutcome
    # The spec file as read, for the backend to parse
    spec_raw: str | None = None
    # Why the PR is REJECTED
    state_cause: str | None = None


class PullRequestParser:
    """
    Reads the spec a pull request carries: the backend names the new spec files under the
    repository's watch_dir, and the only one is read at the merge commit. The backend parses
    and validates the spec.
    """

    def __init__(self, git_api: GitAPI, repo: ProjectTriggerRepository, log):
        self.git_api = git_api
        self.repo = repo
        self.log = log

    def parse(self, pr: PullRequestTrigger) -> ParsedPullRequest:
        """
        REJECTED if the PR has no spec file (the backend fan-out already skips those) or several,
        else READY with the spec file's contents. A git provider failure raises: it is not an outcome.
        """
        spec_files = pr.spec_files
        self.log.info(f"PR #{pr.number} in {self.repo.repo_path}: spec files {spec_files}")

        if not spec_files:
            return ParsedPullRequest(
                outcome=PullRequestOutcome.REJECTED,
                state_cause=f"No new spec file under {self.repo.watch_dir}",
            )
        if len(spec_files) > 1:
            return ParsedPullRequest(
                outcome=PullRequestOutcome.REJECTED,
                state_cause=f"Several new spec files under {self.repo.watch_dir}: {', '.join(spec_files)}",
            )

        contents = self.git_api.get_file_contents(
            repo_path=self.repo.repo_path,
            file_path=spec_files[0],
            ref=pr.merge_commit_sha,
        )
        return ParsedPullRequest(outcome=PullRequestOutcome.READY, spec_raw=contents)
