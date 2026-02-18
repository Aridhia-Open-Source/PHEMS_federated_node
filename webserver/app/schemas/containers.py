from typing import Optional
from pydantic import BaseModel, ConfigDict


class ContainerBase(BaseModel):
    id: int
    name: str
    tag: str|None
    sha: str|None
    ml: bool
    dashboard: bool
    registry_id: int

    model_config = ConfigDict(from_attributes=True)


class ContainerFilters(BaseModel):
    id__lte: Optional[int] = None
    id__gte: Optional[int] = None
    registry_id: Optional[int] = None
    ml: Optional[bool] = None
    dashboard: Optional[bool] = None
    tag: Optional[str] = None
    sha: Optional[str] = None
    name: Optional[str] = None

    page: int = 1
    per_page: int = 25
