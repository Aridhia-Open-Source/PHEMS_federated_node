from enum import Enum

from pydantic import BaseModel, ConfigDict


class PullRequestStatus(str, Enum):
    """Status of a pull request in the ingestion and processing pipeline.

    Internal statuses (set by ingest/trigger sensors):
    - UNKNOWN: Not yet validated
    - IGNORED: Doesn't match watch criteria
    - INVALID: Bad spec or validation failed
    - READY: Validated and handed to Dagster (prevents re-pickup)

    Job lifecycle statuses (mapped from Dagster run events):
    - QUEUED: Dagster job queued
    - STARTED: Dagster job started
    - SUCCESS: Dagster job succeeded
    - FAILURE: Dagster job failed
    - CANCELLED: Dagster job cancelled
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

    repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    spec: dict
    merge_commit_sha: str
    status: str
    dataset_id: int | None = None
    saved_at: str | None = None


class Dataset(BaseModel):
    """Dataset data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    host: str
    port: int
    schema: str | None = None
    schema_write: str | None = None
    type: str
    extra_connection_args: str | None = None
    repository_id: int | None = None
    slug: str
    url: str


class Repository(BaseModel):
    """Repository data from backend API retrieval."""

    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    path: str
    watch_dir: str
    base_branch: str
    default_dataset_name: str | None = None
    initial_cursor: str | None = None
    # created_at: str | None = None
    # updated_at: str | None = None
    pr_cursor: str
    pr_count: int = 0
    pull_requests: list[PullRequest] = []


class Request(BaseModel):
    """Data Access Request from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    title: str
    description: str
    project_name: str
    requested_by: str
    proj_start: str
    proj_end: str
    dataset_id: int
    status: str = "pending"
    created_at: str | None = None
    updated_at: str | None = None
