import re
from sqlalchemy.sql import select
from app.helpers.base_model import Base

FILTERS = [
    'ne',
    'eq',
    'lt',
    'gt',
    'lte',
    'gte',
]


def parse_query_params(model: Base, query_params: dict): # type: ignore
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
    :param query_params: the request args => request.args.copy()
    """
    current_query = select(model)
    for qp_f, qp_v in query_params.items():
        added = False
        for k in FILTERS:
            if re.findall(f'.+__{k}$', qp_f):
                field = qp_f.replace(f'__{k}', '')
                if k == 'ne':
                    current_query = current_query.where(getattr(model, field) != qp_v)
                if k == 'eq':
                    current_query = current_query.where(getattr(model, field) == qp_v)
                if k == 'gt':
                    current_query = current_query.where(getattr(model, field) > qp_v)
                if k == 'lt':
                    current_query = current_query.where(getattr(model, field) < qp_v)
                if k == 'gte':
                    current_query = current_query.where(getattr(model, field) >= qp_v)
                if k == 'lte':
                    current_query = current_query.where(getattr(model, field) <= qp_v)
                added = True
                break
        if not added:
            current_query = current_query.where(getattr(model, qp_f) == qp_v)

    return current_query

