from pydantic import BaseModel, ConfigDict, Field

from fednode.clients.nexus.models.task_compute import TaskCompute


class TaskSpec(BaseModel):
    """What a task runs, from backend API."""
    model_config = ConfigDict(extra="allow")

    image: str
    dataset_id: int | None = None
    env: dict
    compute: TaskCompute = Field(default_factory=TaskCompute)
    tags: dict = {}
    config: dict | None = None
