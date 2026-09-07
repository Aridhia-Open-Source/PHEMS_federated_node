"""Wire models for the backend API responses this code location consumes."""

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, computed_field


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
    spec: dict
    merge_commit_sha: str
    status: str
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
    slug: str
    url: str

    @computed_field
    @property
    def secret_name(self) -> str:
        cleaned_up_host = re.sub('http(s)*://', '', self.host)
        return f"{cleaned_up_host}-{re.sub('\\s|_|#', '-', self.name.lower())}-creds"

    def dump_task_fields(self) -> dict:
        """Return only the fields needed for task configuration with dataset_ prefix."""
        keys = {"name", "host", "port", "type", "schema", "schema_write", "secret_name"}
        fields = self.model_dump(include=keys)
        return {f"dataset_{k}": v for k, v in fields.items()}


class Registry(BaseModel):
    """Container registry data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    url: str
    active: bool = True
    needs_auth: bool = True

    @computed_field
    @property
    def secret_name(self) -> str:
        """The dockerconfigjson secret the backend keeps for this registry."""
        return re.sub(r'[\W_]+', '-', self.host)

    @computed_field
    @property
    def host(self) -> str:
        return re.sub(r'^http(s)?://', '', self.url)

    def matches_image(self, image: str) -> bool:
        return image == self.host or image.startswith(f"{self.host}/")

    @classmethod
    def secret_for_image(cls, image: str, registries: list["Registry"]) -> str | None:
        """
        The pull secret for an image, or None if no configured registry serves it.

        Shortest matching prefix wins, as the backend's own lookup does.
        """
        matches = sorted(
            (r for r in registries if r.matches_image(image)),
            key=lambda r: len(r.host),
        )
        return matches[0].secret_name if matches else None


class TriggerRepository(BaseModel):
    """
    A repository the node watches. Named for which kind it is: the GitHub repo a delivery
    target writes to is the other kind, and lives in delivery_targets.config.
    """

    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    path: str
    watch_dir: str
    base_branch: str
    dataset_id: int
    initial_cursor: str | None = None
    # On the table but not rendered by sanitized_dict(), so these stay None for now.
    request_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    pr_cursor: str
    pr_count: int = 0
    pull_requests: list[PullRequest] = Field(default_factory=list)


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
