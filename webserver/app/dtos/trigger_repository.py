from datetime import datetime

from app.dtos.base import DTO
from app.models.trigger_repository import TriggerRepository


class TriggerRepositoryDTO(DTO):
    id: int
    uri: str
    path: str
    provider: str
    api_uri: str
    k8s_secret_name: str
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
            path=obj.path,
            provider=obj.provider,
            api_uri=obj.api_uri,
            k8s_secret_name=obj.k8s_secret_name,
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
    saved_at: datetime | None
    status: str
    payload: dict


class TaskRequestDTO(DTO):
    id: int
    pull_request_id: int | None
    api_request_id: int | None
    project_id: int
    queued: bool
    payload: dict
