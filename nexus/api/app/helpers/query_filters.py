import re

from fastapi import Request
from sqlalchemy.orm import Query

from app.helpers.base_model import Base
from app.helpers.exceptions import InvalidRequest


FILTERS = [
    'ne',
    'eq',
    'lt',
    'gt',
    'lte',
    'gte',
]


class QueryFilters:
    """Dependency: the request's query string, for parse_query_params."""

    def __init__(self, request: Request):
        self.params = request.query_params

    def copy(self) -> dict:
        return dict(self.params)


def parse_query_params(model: Base, query_params: dict) -> Query: # type: ignore
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
    Parameters
    ----------
    :param model: The Table model to look against the query args
    :param query_params: the request args => filters.copy()
    """
    # The pagination parameters, read by fastapi-pagination, are not filters
    query_params.pop("page", None)
    query_params.pop("size", None)

    current_query = model.query
    for qp_f, qp_v in query_params.items():
        added = False
        field = re.sub(r'(=|__).*', '', qp_f)
        for k in FILTERS:
            if re.findall(f'.+__{k}$', qp_f):
                if k == 'ne':
                    current_query = current_query.filter(getattr(model, field) != qp_v)
                if k == 'eq':
                    current_query = current_query.filter(getattr(model, field) == qp_v)
                if k == 'gt':
                    current_query = current_query.filter(getattr(model, field) > qp_v)
                if k == 'lt':
                    current_query = current_query.filter(getattr(model, field) < qp_v)
                if k == 'gte':
                    current_query = current_query.filter(getattr(model, field) >= qp_v)
                if k == 'lte':
                    current_query = current_query.filter(getattr(model, field) <= qp_v)
                added = True
                break

        if not getattr(model, field, None):
            raise InvalidRequest(f"{field} is not a valid field")

        if not added:
            # We are in the = case
            current_query = current_query.filter(getattr(model, field) == qp_v)

    return current_query

