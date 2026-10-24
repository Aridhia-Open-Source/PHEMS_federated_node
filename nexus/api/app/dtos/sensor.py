from typing import Literal

from app.dtos.base import DTO


class SensorDTO(DTO):
    name: str
    status: Literal["RUNNING", "STOPPED"]
    last_tick: str | None
    error: bool
