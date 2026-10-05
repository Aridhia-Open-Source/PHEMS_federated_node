from datetime import datetime

from app.dtos.base import DTO
from app.dtos.secret import SecretRefDTO
from app.models.trigger_repository import TriggerRepository


class TriggerRepositoryDTO(DTO):
    id: int
    uri: str
    repo_path: str
    provider: str
    api_uri: str
    secret: SecretRefDTO
    watch_dir: str
    base_branch: str
    project_id: int
    dataset_id: int | None
    initial_cursor: datetime | None
    pr_cursor: str
    pr_count: int

    @classmethod
    def from_model(cls, obj: TriggerRepository):
        return cls(
            id=obj.id,
            uri=obj.uri,
            repo_path=obj.repo_path,
            provider=obj.provider,
            api_uri=obj.api_uri,
            secret=SecretRefDTO.from_model(obj.secret),
            watch_dir=obj.watch_dir,
            base_branch=obj.base_branch,
            project_id=obj.project_id,
            dataset_id=obj.dataset.id if obj.dataset else None,
            initial_cursor=obj.initial_cursor,
            pr_cursor=obj.get_pull_request_cursor(),
            pr_count=len(obj.pull_requests),
        )


class PullRequestDTO(DTO):
    trigger_repository_id: int
    number: int
    title: str
    raised_by: str
    merge_commit_sha: str
    merged_at: datetime | None
    state: str
    state_cause: str | None
    task_id: int | None
    payload: dict

