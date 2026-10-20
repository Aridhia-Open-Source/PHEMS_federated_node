from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.dataset import Dataset
from app.models.task import Task


class LaunchDecision(BaseModel):
    """
    The backend's answer to POST /projects/<id>/tasks/<id>/launch: the decision for a PENDING task and, on "launch",
    what the run request is built from. The backend decides; the caller does what the outcome says.

    - outcome: "launch" or "fail".
    - cause: why the task fails; set when the outcome is "fail". The backend has already moved the task to FAILED.
    - task: the task, spec included. On "launch" its spec is what the run config is built from.
    - dataset: the dataset the task runs against, secret reference included; None for a task without one.
    """
    model_config = ConfigDict(extra="allow")

    outcome: Literal["launch", "fail"]
    cause: str | None = None
    task: Task
    dataset: Dataset | None = None
