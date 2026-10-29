from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, PlainSerializer

from app.helpers.base_model import BaseModel as DBModel, Page

WireDatetime = Annotated[
    datetime,
    PlainSerializer(lambda v: v.strftime(DBModel.WIRE_DATETIME_FORMAT), return_type=str),
]


class DTO(BaseModel):
    """
    The response shape of a model. Fields that are not plain attributes of the model
    are filled in by overriding from_model.
    """

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_model(cls, obj) -> Self:
        return cls.model_validate(obj)

    def dump(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)


class PageDTO[T](DTO):
    """The response shape of a list route with pagination, see page_of."""
    items: list[T]
    page: int
    per_page: int
    total: int
    pages: int


def page_of(pagination: Page, dto: type[DTO]) -> dict:
    return {
        "items": [dto.from_model(obj).dump() for obj in pagination.items],
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total": pagination.total,
        "pages": pagination.pages,
    }
