from typing import Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime as dt


class DictionaryBase(BaseModel):
    id: int
    table_name: str
    field_name: str
    label: Optional[str] = None
    description: str
    created_at: dt = dt.now()
    updated_at: Optional[dt] = None

    model_config = ConfigDict(from_attributes=True)


class DictionaryRead(DictionaryBase):
    dataset_id: int


class DictionaryCreate(BaseModel):
    table_name: str
    field_name: str
    description: str
    label: Optional[str] = None
