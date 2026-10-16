from datetime import datetime

from app.dtos.base import DTO
from app.dtos.secret import SecretDTO
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.trigger_repository import TriggerRepository


class TriggerRepositoryDTO(DTO):
    id: int
    uri: str
    provider: str
    api_uri: str
    secret: SecretDTO

    @classmethod
    def from_model(cls, obj: TriggerRepository):
        return cls(
            id=obj.id,
            uri=obj.uri,
            provider=obj.provider,
            api_uri=obj.api_uri,
            secret=SecretDTO.from_model(obj.secret),
        )


class ProjectTriggerRepositoryDTO(DTO):
    """A project's assignment of a global trigger repository, the repository nested."""
    id: int
    project_id: int
    trigger_repository: TriggerRepositoryDTO
    watch_dir: str
    base_branch: str
    dataset_id: int | None
    initial_cursor: datetime | None
    pr_cursor: str
    pr_count: int
    enabled: bool
    revoked: bool
    active: bool

    @classmethod
    def from_model(cls, obj: ProjectTriggerRepository):
        return cls(
            id=obj.id,
            project_id=obj.project_id,
            trigger_repository=TriggerRepositoryDTO.from_model(obj.trigger_repository),
            watch_dir=obj.watch_dir,
            base_branch=obj.base_branch,
            dataset_id=obj.dataset.id if obj.dataset else None,
            initial_cursor=obj.initial_cursor,
            pr_cursor=obj.get_pull_request_cursor(),
            pr_count=len(obj.pull_request_triggers),
            enabled=obj.enabled,
            revoked=obj.revoked,
            active=obj.active,
        )


class PullRequestTriggerDTO(DTO):
    project_id: int
    project_trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merge_commit_sha: str
    merged_at: datetime | None
    state: str
    state_cause: str | None
    task_id: int | None
