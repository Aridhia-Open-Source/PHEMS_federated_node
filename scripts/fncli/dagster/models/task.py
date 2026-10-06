from pydantic import BaseModel, ConfigDict


class Task(BaseModel):
    """Task data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    name: str
    docker_image: str
    status: str | None = None
    attempt: int | None = None
    dagster_run_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    requested_by: str
    dataset_id: int | None = None
    project_id: int
