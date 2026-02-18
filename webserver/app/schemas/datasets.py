import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, computed_field
from typing import List, Optional

import requests

from app.helpers.const import PUBLIC_URL
from app.models.dataset import SUPPORTED_ENGINES
from app.schemas.catalogues import CatalogueCreate
from app.schemas.dictionaries import DictionaryCreate


class DatasetBase(BaseModel):
    id: int
    name: str
    host: str
    port: int = 5432
    schema_read: Optional[str] = Field(None, alias="schema")
    schema_write: Optional[str] = None
    type: str = "postgres"
    extra_connection_args: Optional[str] = None
    repository: Optional[str] = None


class DatasetCreate(BaseModel):
    username: str
    password: str
    name: str
    host: str
    port: int = 5432
    schema_read: Optional[str] = Field(None, alias="schema_name")
    schema_write: Optional[str] = None
    type: str = "postgres"
    extra_connection_args: Optional[str] = None
    repository: Optional[str] = None

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


class DatasetRead(DatasetBase):
    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def url(self) -> str:
        return f"https://{PUBLIC_URL}/datasets/{self.slug}"

    @computed_field
    @property
    def slug(self) -> str:
        """
        Based on the provided name, it will return the slugified name
        so that it will be sade to save on the DB
        """
        return re.sub(r'[\W_]+', '-', self.name)


class DatasetFilters(BaseModel):
    id__lte: Optional[int] = None
    id__gte: Optional[int] = None
    name: Optional[str] = None
    host: Optional[str] = None
    type: Optional[str] = None
    repository: Optional[str] = None

    page: int = 1
    per_page: int = 25
