"""
request-related endpoints:
- GET /requests
- POST /requests
- GET /code/approve
"""
from http import HTTPStatus
import json
from typing import Any
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session as DBSession
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.wrappers import Auth, audit
from app.helpers.base_model import get_db
from app.models.dataset import Dataset
from app.models.request import RequestModel
from app.schemas.requests import TransferTokenBody


router = APIRouter(tags=["requests"], prefix="/requests")


@router.get('',
            dependencies=[Depends(Auth("can_admin_request"))],
            deprecated=True)
@audit
async def get_requests(request: Request, session: DBSession = Depends(get_db)) -> list:
    """
    GET /requests endpoint. Gets a list of Data Access RequestModel
    """
    res = RequestModel.get_all(session)
    if res:
        res = [r[0].sanitized_dict() for r in res]
    return res

# Disabled for the time being, also disable the pylint rule for duplicated code
@router.post(
        '',
        dependencies=[Depends(Auth("can_send_request"))],
        status_code=HTTPStatus.CREATED,
        deprecated=True
    )
# pylint: disable=R0801
@audit
async def post_requests(
    request: Request,
    body: TransferTokenBody,
    session: DBSession = Depends(get_db)
) -> dict[str, Any]:
    """
    POST /requests/ endpoint. Creates a new Data Access RequestModel
    """
    try:
        body["requested_by"] = json.dumps(body["requested_by"])
        ds_id = getattr(body, "dataset_id", None)
        ds_name = getattr(body,"dataset_name", None)
        body.dataset = Dataset.get_dataset_by_name_or_id(ds_id, ds_name)

        req_attributes = RequestModel.validate(body)
        req = RequestModel(**req_attributes)
        req.add(session)
        return {"request_id": req.id}
    except KeyError as kexc:
        session.rollback()
        raise InvalidRequest(
            "Missing field. Make sure \"catalogue\" and \"dictionary\" entries are there"
        ) from kexc
    except:
        session.rollback()
        raise

# Disabled for the time being, also disable the pylint rule for duplicated code
@router.post(
        '/{code}/approve',
        dependencies=[Depends(Auth("can_admin_request"))],
        status_code=HTTPStatus.CREATED,
        deprecated=True
    )
# pylint: disable=R0801
@audit
async def post_approve_requests(code: int, request: Request) -> dict[str, str]:
    """
    POST /requests/code/approve endpoint. Approves a pending Data Access RequestModel
    """
    dar = RequestModel.get_by_id(id=code)
    if dar is None:
        raise DBRecordNotFoundError(f"Data Access RequestModel {code} not found")

    if dar.status == dar.STATUSES["approved"]:
        return {"message": "RequestModel already approved"}

    user_info = dar.approve()
    return user_info
