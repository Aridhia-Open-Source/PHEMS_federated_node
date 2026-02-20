from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import List, Optional

import requests

from app.models.dataset import SUPPORTED_ENGINES, Dataset
from app.schemas.catalogues import CatalogueCreate
from app.schemas.dictionaries import DictionaryCreate
from app.helpers.exceptions import InvalidRequest


class DatasetBase(BaseModel):
    name: str
    host: str
    port: int = 5432
    schema_read: Optional[str] = None
    schema_write: Optional[str] = None
    type: str = "postgres"
    extra_connection_args: Optional[str] = None
    repository: Optional[str] = None


class DatasetCreate(DatasetBase):
    username: str
    password: str

    catalogue: Optional[CatalogueCreate] = None
    dictionaries: List[DictionaryCreate] = Field(default_factory=list)

    @field_validator('name')
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return requests.utils.unquote(v).lower()

    @field_validator('repository')
    @classmethod
    def sanitize_repo(cls, v: Optional[str]) -> Optional[str]:
        return v.lower() if v else v

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str):
        if v.lower() not in SUPPORTED_ENGINES:
            raise ValueError(f"DB type {v} is not supported.")
        return v

    @field_validator('repository')
    @classmethod
    def validate_repo(cls, v: str):
        if Dataset.query.filter_by(repository=v).one_or_none():
            raise ValueError(
                "Repository is already linked to another dataset. Please PATCH that dataset with repository: null"
            )
        return v


class DatasetUpdate(DatasetCreate):
    # Host not allowed to be updated
    host: None = None
    username: Optional[str] = None
    password: Optional[str] = None
    name: Optional[str] = None


class DatasetRead(DatasetBase):
    id: int
    url: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class DatasetFilters(BaseModel):
    id__lte: Optional[int] = None
    id__gte: Optional[int] = None
    name: Optional[str] = None
    host: Optional[str] = None
    type: Optional[str] = None
    repository: Optional[str] = None

    page: int = 1
    per_page: int = 25
