from typing import Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime as dt


class CatalogueBase(BaseModel):
    id: int
    version: str
    title: str
    description: str
    created_at: dt = dt.now()
    updated_at: Optional[dt] = None

    model_config = ConfigDict(from_attributes=True)


class CatalogueRead(CatalogueBase):
    dataset_id: int


class CatalogueCreate(BaseModel):
    version: str
    title: str
    description: str
