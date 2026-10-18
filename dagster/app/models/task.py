from pydantic import BaseModel, ConfigDict

from app.models.task_spec import TaskSpec


class Task(BaseModel):
    """Task data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    spec: TaskSpec
    attempt: int
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    requested_by: str
    project_id: int
    trigger_id: int
    executor_run_id: str | None = None
    exit_code: int | None = None
    state_cause: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
