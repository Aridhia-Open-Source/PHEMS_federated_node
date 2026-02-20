from sqlalchemy import func, DateTime
from pydantic import BaseModel


def apply_filters(model, filter_dto: BaseModel):
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
    query = model.query
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
        query = query.filter(operators[op_name](column, value))

    return query.paginate(page=filter_dto.page, per_page=filter_dto.per_page)
