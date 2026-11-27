from datetime import datetime
from typing import Annotated, Self

from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer
from sqlalchemy.orm import Query

from app.database.base_model import BaseModel as DBModel

WireDatetime = Annotated[
    datetime,
    PlainSerializer(lambda v: v.strftime(DBModel.WIRE_DATETIME_FORMAT), return_type=str),
]


def _naive_utc(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value.rstrip('Z'))
    raise ValueError("must be an ISO 8601 datetime string")


# A request's timestamp: an ISO 8601 string, stored without a time zone, as UTC, like every other timestamp
NaiveUtcDatetime = Annotated[datetime, BeforeValidator(_naive_utc)]


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


def page_of(query: Query, dto: type[DTO]) -> Page[DTO]:
    """A page of the query's rows as dto, per the page and size parameters (see add_pagination in the app factory)."""
    return paginate(query, transformer=lambda rows: [dto.from_model(row) for row in rows])
