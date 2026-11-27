from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.dtos.base import DTO

SensorStatus = Literal["RUNNING", "STOPPED"]


class SensorDTO(DTO):
    name: str
    status: SensorStatus
    last_tick: str | None
    error: bool


class SensorStatusRequest(BaseModel):
    """The status to set on a sensor."""
    model_config = ConfigDict(extra="forbid")

    status: SensorStatus


class SensorsStatusRequest(SensorStatusRequest):
    """The status to set on every sensor, or only on those in names."""
    names: list[str] | None = None
