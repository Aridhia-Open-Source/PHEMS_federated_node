"""
admin endpoints:
- GET /audit
"""

from flask import Blueprint, request
from sqlalchemy.orm import scoped_session, sessionmaker

from .helpers.wrappers import auth
from .helpers.base_model import engine
from .helpers.query_filters import parse_query_params

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
    query = parse_query_params(Audit, request.args.copy())
    res = session.execute(query).all()
    if res:
        res = [r[0].sanitized_dict() for r in res]
    return res, 200
