# TODO(DAR): the DTO was removed while this is disconnected; restore DARDTO from git history
# (commit fd5cf66a) before re-attaching.
"""
request-related endpoints:
- GET /requests
- POST /requests
- GET /code/approve
"""
import json
from http import HTTPStatus

from flask import Blueprint, request

from app.helpers.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.query_filters import parse_query_params
from app.helpers.wrappers import audit, auth
from app.models.dataset import Dataset
from app.models.extras.dar import DAR

# TODO(DAR): not registered in app/__init__.py, disconnected for now.
bp = Blueprint('requests', __name__, url_prefix='/requests')
session = db.session


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_request')
def get_requests():
    """
    GET /requests/ endpoint. Gets a list of Data Access Request
    """
    paginated = parse_query_params(DAR, request.args.copy())
    res = [DARDTO.from_model(r).dump() for r in paginated.items]
    return res, HTTPStatus.OK

# Disabled for the time being, also disable the pylint rule for duplicated code
# @bp.route('/', methods=['POST'])
# pylint: disable=R0801
@audit
@auth(scope='can_send_request')
def post_requests():
    """
    POST /requests/ endpoint. Creates a new Data Access Request
    """
    try:
        body = request.json
        if 'email' not in body["requested_by"].keys():
            raise InvalidRequest("Missing email from requested_by field")

        body["requested_by"] = json.dumps(body["requested_by"])
        ds_id = body.pop("dataset_id")
        body["dataset"] = session.get(Dataset, ds_id)
        if body["dataset"] is None:
            raise DBRecordNotFoundError(f"Dataset {ds_id} not found")

        req_attributes = DAR.validate(body)
        req = DAR(**req_attributes)
        req.add()
        return {"request_id": req.id}, HTTPStatus.CREATED
    except KeyError as kexc:
        session.rollback()
        raise InvalidRequest(
            "Missing field. Make sure \"catalogue\" and \"dictionary\" entries are there"
        ) from kexc
    except Exception:
        session.rollback()
        raise

# Disabled for the time being, also disable the pylint rule for duplicated code
# @bp.route('/<code>/approve', methods=['POST'])
# pylint: disable=R0801
@audit
@auth(scope='can_admin_request')
def post_approve_requests(code):
    """
    POST /requests/code/approve endpoint. Approves a pending Data Access Request
    """
    dar = session.get(DAR, code)
    if dar is None:
        raise DBRecordNotFoundError(f"Data Access Request {code} not found")

    if dar.status == dar.STATUSES["approved"]:
        return {"message": "Request already approved"}, HTTPStatus.OK

    user_info = dar.approve()
    return user_info, HTTPStatus.CREATED
