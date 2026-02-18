from typing import Optional
from pydantic import BaseModel, ConfigDict


class RegistryBase(BaseModel):
    id: int
    url: str
    needs_auth: bool
    active: bool

    model_config = ConfigDict(from_attributes=True)


class RegistryFilters(BaseModel):
    id__lte: Optional[int] = None
    id__gte: Optional[int] = None
    url: Optional[str] = None
    active: Optional[bool] = None

    page: int = 1
    per_page: int = 25
