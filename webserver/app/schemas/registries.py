from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import select

from app.helpers.exceptions import InvalidRequest
from app.models.registry import Registry
from app.helpers.base_model import get_db


class RegistryBase(BaseModel):
    url: str
    needs_auth: bool = True
    active: bool = True

    model_config = ConfigDict(from_attributes=True)


class RegistryCreate(RegistryBase):
    username: str
    password: str


class RegistryUpdate(RegistryCreate):
    # url won't be allowed, by setting it to None,
    # it will be excluded through model_dump(exclude_unset=True)
    url: None = None
    needs_auth: Optional[bool] = None
    active: Optional[bool] = None
    username: Optional[str] = None
    password: Optional[str] = None


class RegistryRead(RegistryBase):
    id: int


class RegistryFilters(BaseModel):
    id__lte: Optional[int] = None
    id__gte: Optional[int] = None
    url: Optional[str] = None
    active: Optional[bool] = None

    page: int = 1
    per_page: int = 25
