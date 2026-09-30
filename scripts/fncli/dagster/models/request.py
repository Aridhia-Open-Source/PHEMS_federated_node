from pydantic import BaseModel, ConfigDict


class Request(BaseModel):
    """Data Access Request from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    title: str
    description: str | None = None
    project_name: str
    requested_by: str
    proj_start: str
    proj_end: str
    project_id: int | None = None
    dataset_id: int | None = None
    status: str = "pending"
    created_at: str | None = None
    updated_at: str | None = None
