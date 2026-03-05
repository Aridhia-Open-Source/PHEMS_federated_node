from typing import Any

from sqlalchemy import func, DateTime, select
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.helpers.base_model import BaseModel as DBBaseModel


def apply_filters(
        db: Session,
        model: DBBaseModel,
        filter_dto: BaseModel,
        as_pagination:bool = True
    )-> dict[str, Any] | Any:
    """
    We aim to convert query strings in models fields
    to be used as filters.
    The filters follow the python Django filtering system
        - __lte => less than or equal
        - __gte => greater than or equal
        - =     => equal
        - __eq  => equal
        - __gt  => greater than
        - __lt  => less than
        - __ne  => not equal
    """
    query = select(model)
    # filter_dto.model_dump(exclude_none=True) gives us only what the user sent
    filters = filter_dto.model_dump(exclude={"page", "per_page"}, exclude_none=True)

    operators = {
        "lte": lambda col, val: col <= val,
        "gte": lambda col, val: col >= val,
        "gt":  lambda col, val: col > val,
        "lt":  lambda col, val: col < val,
        "ne":  lambda col, val: col != val,
        "eq":  lambda col, val: col == val,
    }

    for key, value in filters.items():
        if "__" in key:
            field_name, op_name = key.split("__")
        else:
            field_name, op_name = key, "eq"

        column = getattr(model, field_name)
        if column.type.__class__ == DateTime:
            column = func.date(column)
        query = query.where(operators[op_name](column, value))

    items = db.execute(query).scalars().all()
    total = len(items)

    if as_pagination:
        start_idx = filter_dto.per_page * (filter_dto.page - 1)
        return {
            "items": items[start_idx: start_idx + filter_dto.per_page],
            "total": total,
            "page": filter_dto.page,
            "per_page": filter_dto.per_page,
            "pages": (total + filter_dto.per_page - 1) // filter_dto.per_page
        }
    return query
