from enum import Enum

from pydantic import BaseModel, ConfigDict


class PullRequestStatus(str, Enum):
    """Status of a pull request in the ingestion and processing pipeline."""

    UNPROCESSED = "unprocessed"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"

    def __str__(self):
        return self.value


class PullRequest(BaseModel):
    """Pull Request data from backend API."""
    model_config = ConfigDict(extra="allow")

    repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    spec: dict
    merge_commit_sha: str
    is_valid: bool
    status: str


class Repository(BaseModel):
    """Repository data from backend API retrieval."""

    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    path: str
    watch_dir: str
    base_branch: str
    last_merged_at: str
    pull_requests: list[PullRequest] = []
