from pydantic import BaseModel, ConfigDict

from fncli.dagster.models.task_spec import TaskSpec


class Task(BaseModel):
    """Task data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    spec: TaskSpec
    status: str | None = None
    attempt: int | None = None
    dagster_run_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    requested_by: str
    project_id: int
