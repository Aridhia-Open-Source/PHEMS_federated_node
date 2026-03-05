from pydantic import BaseModel, ConfigDict, Field, field_validator, computed_field, model_validator
from datetime import datetime as dt
from typing import Optional, Self

from sqlalchemy import func, select

from app.helpers.base_model import get_db
from app.helpers.exceptions import InvalidRequest
from app.helpers.keycloak import Keycloak
from app.models.dataset import Dataset
from app.models.request import RequestModel


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
    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str
    description: Optional[str] = None
    requested_by: dict
    project_name: str
    status: Optional[str] = "pending"
    proj_start: Optional[dt] = None
    proj_end: Optional[dt] = None
    dataset_id: Optional[int] = None
    dataset_name: Optional[str] = Field(default=None, exclude=True)

    @field_validator('requested_by')
    @classmethod
    def validate_requested_by(cls, v: dict) -> str:
        if 'email' not in v:
            raise InvalidRequest("Missing email from requested_by field")

        user: dict = Keycloak().get_user_by_email(v["email"])
        if not user:
            user = Keycloak().create_user(**v)

        return user["id"]

    @computed_field
    @property
    def dataset(self) -> Dataset:
        return Dataset.get_dataset_by_name_or_id(self.dataset_id, self.dataset_name)

    @model_validator(mode='after')
    def extract_fields(self) -> Self:
        q = select(RequestModel).where(
            RequestModel.project_name == self.project_name,
            RequestModel.proj_end >= func.now(),
            RequestModel.requested_by == self.requested_by
        )
        with get_db() as session:
            overlaps = session.execute(q).scalars().all()

        if overlaps:
            raise InvalidRequest(f"User already belongs to the active project {self.project_name}")

        return self
