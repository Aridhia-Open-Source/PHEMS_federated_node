from http.client import HTTPException
import logging
from functools import wraps
from typing import Annotated
from fastapi import Depends, Header, Request, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.helpers.exceptions import AuthenticationError, UnauthorizedError
from app.helpers.keycloak import Keycloak
from app.models.audit import Audit
from app.models.dataset import Dataset
from app.models.request import RequestModel
from app.helpers.base_model import get_db


logger = logging.getLogger('wrappers')
logger.setLevel(logging.INFO)


class Auth:
    def __init__(self, scope: str, check_dataset: bool = False):
        self.scope = scope
        self.check_dataset = check_dataset

    async def __call__(self,
                       dataset_id: int|None = None,
                       dataset_name: str|None = None,
                       session: Session = Depends(get_db),
                       Authorization: Annotated[str | None, Header()] = None,
                       project_name: Annotated[str | None, Header()] = None
            ) -> dict:
        if not Authorization:
            raise AuthenticationError()

        token = Authorization.replace("Bearer ", "")
        if self.scope and not token:
            raise AuthenticationError("Token not provided")

        resource = 'endpoints'
        client = 'global'
        token_type = 'refresh_token'

        kc_client = Keycloak()
        token_info = kc_client.decode_token(token)
        user = kc_client.get_user_by_username(token_info['username'])

        if project_name and not kc_client.is_user_admin(token):
            dar: RequestModel = RequestModel.get_active_project(session, project_name, user["id"])
            if dar.dataset_id:
                ds = Dataset.get_dataset_by_name_or_id(session, id=dar.dataset_id)
                resource = f"{ds.id}-{ds.name}"

        elif self.check_dataset:
            if Request.is_json and Request.data:
                flat_json = flatten_dict(Request.json)
                dataset_id = flat_json.get("dataset_id")
                dataset_name = flat_json.get("dataset_name", "")

            if dataset_id or dataset_name:
                ds = Dataset.get_dataset_by_name_or_id(session, name=dataset_name, id=dataset_id)
                resource = f"{ds.id}-{ds.name}"

        # If the user is an admin or system, ignore the project
        if not kc_client.has_user_roles(user["id"], {"Super Administrator", "Administrator", "System"}):
            if project_name:
                client = f"RequestModel {token_info['username']} - {project_name}"
                kc_client = Keycloak(client)
                token = kc_client.exchange_global_token(token)
                token_type = 'access_token'

        if kc_client.is_token_valid(token, self.scope, resource, token_type):
            return user
        else:
            raise UnauthorizedError("Token is not valid, or the user has not enough permissions.")


def audit(func):
    @wraps(func)
    async def _audit(*args, **kwargs):
        request: Request = kwargs.get("request")
        session: Request = kwargs.get("session")
        body: Session = kwargs.get("body", "No body")
        if isinstance(body, BaseModel):
            body = body.model_dump()

        raised_exception = None
        audit_body = {}
        http_status = 200
        try:
            response_object = await func(*args, **kwargs)
            if isinstance(response_object, Response):
                http_status = response_object.status_code
        except HTTPException as exc:
            response_object = { "error": exc.description }
            http_status = exc.code
            raised_exception = exc
        except IntegrityError as inte:
            response_object = { "error": "Record already exists" }
            http_status = 500
            raised_exception = inte

        audit_body["status_code"] = http_status

        if 'HTTP_X_REAL_IP' in request.headers:
            # if behind a proxy
            audit_body["ip_address"] = request.headers['HTTP_X_REAL_IP']
        else:
            audit_body["ip_address"] = request.scope["client"][0]

        if body:
            audit_body["details"] = body
            # details should include the request body. If a json and the body is not empty
            # Remove any of the following fields that contain
            # sensitive data, so far only username and password on dataset POST
            for field in ["username", "password"]:
                find_and_redact_key(body, field)
            audit_body["details"] = str(body)

        audit_body["requested_by"] = "No auth"
        if "Authorization" in request.headers:
            kc_client = Keycloak()
            token = kc_client.decode_token(Keycloak.get_token_from_headers(request))
            audit_body["requested_by"] = kc_client.get_user_by_email(token["email"])["id"]

        audit_body["http_method"] = request.method
        audit_body["endpoint"] = request.scope["path"]
        audit_body["api_function"] = func.__name__
        to_save = Audit(**audit_body)
        if not session:
            with get_db() as session:
                to_save.add(session)
        else:
            to_save.add(session)
        if raised_exception:
            raise raised_exception

        return response_object
    return _audit


def find_and_redact_key(obj: dict|str, key: str):
    """
    Given a dictionary, tries to find a (nested) key and redact its value
    """
    if isinstance(obj, str):
        return

    for k, v in obj.items():
        if isinstance(v, dict):
            find_and_redact_key(v, key)
        elif isinstance(v, list):
            for item in obj[k]:
                if isinstance(item, dict):
                    find_and_redact_key(item, key)
        elif k == key:
            obj[k] = '*****'

def flatten_dict(to_flatten:dict) -> dict:
    """
    Does exactly what the name means. If a value is an array of dicts
    it will stay untouched.
    """
    flat = dict()
    for k, v in to_flatten.items():
        if isinstance(v, dict):
            flat[k] = {}
            flat.update(flatten_dict(v))
        else:
            flat[k] = v
    return flat
