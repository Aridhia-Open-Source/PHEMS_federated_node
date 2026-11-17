from pydantic import BaseModel, ConfigDict


class Project(BaseModel):
    """Project data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    # The nexus operator's user when its custom resource declares the record (ADR 0032)
    managed_by: str | None = None
    name: str
    description: str | None = None
    enabled: bool = False
    default_dataset_id: int | None = None
    results_repository_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
