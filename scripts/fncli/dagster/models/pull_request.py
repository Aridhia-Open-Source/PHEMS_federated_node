from enum import Enum

from pydantic import BaseModel, ConfigDict


class PullRequestStatus(str, Enum):
    """
    UNKNOWN | IGNORED | INVALID | READY are the ingest lifecycle; the rest are job state,
    which belongs on tasks.status. They stay here while the sensors still write them.
    pull_requests.status has no database constraint, so dropping them is a code change.
    """

    UNKNOWN = "UNKNOWN"
    IGNORED = "IGNORED"
    INVALID = "INVALID"
    READY = "READY"
    QUEUED = "QUEUED"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"

    def __str__(self):
        return self.value


class PullRequest(BaseModel):
    """Pull Request data from backend API."""
    model_config = ConfigDict(extra="allow")

    trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    payload: dict
    merge_commit_sha: str
    status: str
    saved_at: str | None = None
