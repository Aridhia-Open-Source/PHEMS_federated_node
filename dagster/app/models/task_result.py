from pydantic import BaseModel, ConfigDict

from app.models.task_result_status import TaskResultStatus


class TaskResult(BaseModel):
    """The delivery of one task's results to one results repository."""
    model_config = ConfigDict(extra="allow")

    id: int
    task_id: int
    results_repository_id: int
    status: TaskResultStatus
    attempts: int
    branch: str | None = None
    commit_sha: str | None = None
    pull_request_number: int | None = None
    pull_request_url: str | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
