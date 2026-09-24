"""
admin endpoints:
- GET /audit
- PATCH /delivery-secret
"""

from http import HTTPStatus
from flask import Blueprint, request
from sqlalchemy.orm import scoped_session, sessionmaker

from .helpers.base_model import engine
from .helpers.exceptions import NotImplementedException
from .helpers.query_filters import parse_query_params
from .helpers.wrappers import audit, auth
from .models.audit import Audit


bp = Blueprint('admin', __name__, url_prefix='/')
session_factory = sessionmaker(bind=engine)
session = scoped_session(session_factory)


@bp.route('/audit', methods=['GET'])
@auth(scope='can_do_admin', check_dataset=False)
def get_audit_logs():
    """
    GET /audit endpoint.
        Returns a list of audit entries
    """
    return parse_query_params(Audit, request.args.copy()), HTTPStatus.OK

@bp.route('/delivery-secret', methods=['PATCH'])
@auth(scope='can_do_admin', check_dataset=False)
@audit
def update_delivery_secret():
    """
    PATCH /delivery-secret
        Updates the results delivery secret
    """
    raise NotImplementedException()
