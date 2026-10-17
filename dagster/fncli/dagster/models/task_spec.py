from pydantic import BaseModel, ConfigDict


class TaskSpec(BaseModel):
    """What a task runs, from backend API."""
    model_config = ConfigDict(extra="allow")

    image: str
    dataset_id: int | None = None
    env: dict
