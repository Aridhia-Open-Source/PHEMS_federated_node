from typing import Literal

from pydantic import BaseModel, ConfigDict


class TaskConfig(BaseModel):
    """
    The backend's answer to GET /projects/<id>/tasks/<id>/config: the decision for a PENDING task.

    - outcome: "launch" or "fail". The backend decides; the caller does what it says.
    - cause: why the task fails; set when the outcome is "fail".
    - revoked, current, changes, config_hash, config_snapshot: the facts behind it, for delivery and display.
    """
    model_config = ConfigDict(extra="allow")

    outcome: Literal["launch", "fail"]
    cause: str | None = None
    revoked: list[str] = []
    current: bool = True
    changes: list[str] = []
    config_hash: str | None = None
    config_snapshot: dict | None = None
