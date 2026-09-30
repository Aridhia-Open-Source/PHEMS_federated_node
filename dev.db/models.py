"""Data models for backend API."""

from enum import Enum
from pydantic import BaseModel, ConfigDict


class PullRequestStatus(str, Enum):
    """Status of a pull request in the ingestion and processing pipeline."""

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
    spec: dict
    merge_commit_sha: str
    status: str


class Project(BaseModel):
    """Project data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    description: str | None = None
    default_dataset_id: int | None = None


class K8sSecret(BaseModel):
    """Reference to a Kubernetes secret, from the backend API. The values are never returned."""
    model_config = ConfigDict(extra="allow")

    id: int
    name: str


class Dataset(BaseModel):
    """Dataset data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    host: str
    port: int
    read_schema: str | None = None
    write_schema: str | None = None
    type: str
    extra_connection_args: str | None = None
    project_id: int
    k8s_secret_name: str
    slug: str
    url: str


class TriggerRepository(BaseModel):
    """Trigger repository data from backend API retrieval."""

    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    path: str
    watch_dir: str
    base_branch: str
    dataset_id: int
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
