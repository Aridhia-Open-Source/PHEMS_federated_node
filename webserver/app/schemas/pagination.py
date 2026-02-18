from pydantic import BaseModel, ConfigDict
from typing import Generic, List, TypeVar


T = TypeVar("T")

class PageResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    per_page: int
    pages: int

    model_config = ConfigDict(from_attributes=True)
