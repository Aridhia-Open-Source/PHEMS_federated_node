from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime as dt
from typing import Optional

from app.helpers.exceptions import InvalidRequest
from app.models.dataset import Dataset
from app.schemas.datasets import DatasetRead


class RequestSchema(BaseModel):
    id: int
    title: str
    project_name: str
    requested_by: str
    description: str
    status: str
    proj_start: dt
    proj_end: dt
    created_at: dt
    updated_at: dt

    model_config = ConfigDict(from_attributes=True)


class TransferTokenBody(BaseModel):
    title: str
    description: Optional[str] = None
    requested_by: dict
    project_name: str
    status: Optional[str] = "pending"
    proj_start: Optional[dt] = None
    proj_end: Optional[dt] = None
    dataset: Optional[DatasetRead]

    @field_validator('requested_by')
    @classmethod
    def validate_requested_by(cls, v: dict):
        if 'email' not in v:
            raise InvalidRequest("Missing email from requested_by field")

        return v
