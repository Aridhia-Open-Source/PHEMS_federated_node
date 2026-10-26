from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.dtos.base import DTO
from app.dtos.git_provider import GitProviderRefDTO
from app.dtos.secret import SecretDTO
from app.helpers.exceptions import InvalidRequest
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.trigger_repository import TriggerRepository


class TriggerRepositoryDTO(DTO):
    id: int
    uri: str
    repo_path: str
    provider: GitProviderRefDTO
    secret: SecretDTO
    enabled: bool
    revoked: bool
    # Where polling the provider resumes, see TriggerRepository.get_ingest_cursor
    pr_cursor: str

    @classmethod
    def from_model(cls, obj: TriggerRepository):
        return cls(
            id=obj.id,
            uri=obj.uri,
            repo_path=obj.repo_path,
            provider=GitProviderRefDTO.from_model(obj.provider),
            secret=SecretDTO.from_model(obj.secret),
            enabled=obj.enabled,
            revoked=obj.revoked,
            pr_cursor=obj.get_ingest_cursor(),
        )


class TriggerRepositoryRefDTO(DTO):
    """A trigger repository named by where it is, without its secret or cursor."""
    id: int
    repo_path: str
    uri: str


class ProjectTriggerRepositoryDTO(DTO):
    """A project's resource for a global trigger repository, the repository nested. Addressed by the repository's id."""
    project_id: int
    trigger_repository: TriggerRepositoryDTO
    watch_dir: str
    base_branch: str
    dataset_id: int | None
    pr_cursor: str
    pr_count: int
    enabled: bool
    revoked: bool
    active: bool

    @classmethod
    def from_model(cls, obj: ProjectTriggerRepository):
        return cls(
            project_id=obj.project_id,
            trigger_repository=TriggerRepositoryDTO.from_model(obj.trigger_repository),
            watch_dir=obj.watch_dir,
            base_branch=obj.base_branch,
            dataset_id=obj.dataset.id if obj.dataset else None,
            pr_cursor=obj.get_pull_request_cursor(),
            pr_count=len(obj.pull_request_triggers),
            enabled=obj.enabled,
            revoked=obj.revoked,
            active=obj.active,
        )


class PullRequestDTO(DTO):
    """The provider's facts of a pull request, stored once per repository."""
    id: int
    trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: datetime
    merge_commit_sha: str
    base_branch: str
    files_truncated: bool


class PullRequestBatchDTO(DTO):
    """The response of storing a batch of pull requests: the numbers stored, and those already there."""
    created: list[int]
    existing: list[int]


class PullRequestTriggerDTO(DTO):
    project_id: int
    trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merge_commit_sha: str
    merged_at: datetime | None
    state: str
    state_cause: str | None
    task_id: int | None
    # Paths of the new spec files under the project resource's watch_dir; the evaluate step reads from these
    spec_files: list[str]


class TaskTriggerDTO(PullRequestTriggerDTO):
    """The pull request that yielded a task, with the repository it was merged in nested."""
    trigger_repository: TriggerRepositoryRefDTO

    @classmethod
    def from_model(cls, obj: PullRequestTrigger):
        return cls(
            **PullRequestTriggerDTO.from_model(obj).model_dump(),
            trigger_repository=TriggerRepositoryRefDTO.from_model(obj.project_trigger_repository.trigger_repository),
        )


class ChangedFileRequest(BaseModel):
    """A file a pull request changed: its path and how it changed, never its content."""
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=1024)
    status: str = Field(min_length=1, max_length=32)


class PullRequestRequest(BaseModel):
    """A merged pull request as ingested: the provider's facts and the paths it changed."""
    model_config = ConfigDict(extra="forbid", strict=True)

    number: int = Field(ge=1)
    title: str = Field(max_length=256)
    raised_by: str = Field(max_length=256)
    merged_at: datetime
    merge_commit_sha: str = Field(min_length=1, max_length=40)
    base_branch: str = Field(min_length=1, max_length=256)
    files_truncated: bool
    changed_files: list[ChangedFileRequest]

    @field_validator("merged_at", mode="before")
    @classmethod
    def naive_utc(cls, value):
        """Stored without a time zone, as UTC, like every other timestamp."""
        if isinstance(value, str):
            return datetime.fromisoformat(value.rstrip('Z'))
        raise ValueError("merged_at must be an ISO 8601 datetime string")

    @classmethod
    def parse(cls, body) -> "PullRequestRequest":
        try:
            return cls.model_validate(body)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid pull request: {ve}") from ve
