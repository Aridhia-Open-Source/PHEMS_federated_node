import logging
from functools import wraps
from flask import request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.helpers.db import db, engine
from app.helpers.exceptions import AuthenticationError, UnauthorizedError, DBRecordNotFoundError, LogAndException
from app.helpers.keycloak import Keycloak
from app.models.audit import Audit


logger = logging.getLogger('wrappers')
logger.setLevel(logging.INFO)

def auth(scope:str, check_dataset=True):
    def auth_wrapper(func):
        @wraps(func)
        def _auth(*args, **kwargs):
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if scope and not token:
                raise AuthenticationError("Token not provided")

            session = db.session
            resource = 'endpoints'
            ds_id = None
            if check_dataset:
                path = request.path.split('/')

                if 'datasets' in path and len(path) > 2:
                    ds_id = path[path.index('datasets') + 1]
                elif request.headers.get('Content-Type'):
                    ds_id = request.json.get("dataset_id")

                if ds_id and check_dataset:
                    q = session.execute(text("SELECT * FROM datasets WHERE id=:ds_id"), dict(ds_id=ds_id)).all()
                    if not q:
                        raise DBRecordNotFoundError(f"Dataset with id {ds_id} does not exist")
                    ds = q[0]._mapping
                    if ds is not None:
                        resource = f"{ds["id"]}-{ds["name"]}"
            requested_project = request.headers.get("project-name")
            client = 'global'
            token_type = 'refresh_token'
            if requested_project:
                token_info = Keycloak().decode_token(token)
                client = f"Request {token_info['username']} - {requested_project}"
                token = Keycloak(client).exchange_global_token(token)
                token_type = 'access_token'

            if Keycloak(client).is_token_valid(token, scope, resource, token_type):
                return func(*args, **kwargs)
            else:
                raise UnauthorizedError("Token is not valid, or the user has not enough permissions.")
        return _auth
    return auth_wrapper


session = Session(engine)

def audit(func):
    @wraps(func)
    def _audit(*args, **kwargs):
        try:
            response_object, http_status = func(*args, **kwargs)
        except LogAndException as exc:
            response_object = { "error": exc.description }
            http_status = exc.code
        except IntegrityError as exc:
            response_object = { "error": "Record already exists" }
            http_status = 500

        if 'HTTP_X_REAL_IP' in request.environ:
            # if behind a proxy
            source_ip = request.environ['HTTP_X_REAL_IP']
        else:
            source_ip = request.environ['REMOTE_ADDR']

        details = None
        # details should include the request body. If a json
        if request.is_json:
            details = request.json
            # Remove any of the following fields that contain
            # sensitive data, so far only username and password on dataset POST
            for field in ["username", "password"]:
                find_and_redact_key(details, field)
            details = str(details)
        elif request.data:
            details = request.data.decode()

        requested_by = ""
        if "Authorization" in request.headers:
            token = Keycloak().decode_token(Keycloak.get_token_from_headers())
            requested_by = token.get('sub')

        http_method = request.method
        http_endpoint = request.path
        api_function = func.__name__
        to_save = Audit(source_ip, http_method, http_endpoint, requested_by, http_status, api_function, details)
        to_save.add()
        return response_object, http_status
    return _audit

def find_and_delete_key(obj: dict, key: str):
    """
    Given a dictionary, tries to find a (nested) key and pops it
    """
    copy_obj = obj.copy()
    for k, v in copy_obj.items():
        if isinstance(v, dict):
            find_and_delete_key(v, key)
        elif isinstance(v, list):
            for item in obj[k]:
                if isinstance(item, dict):
                    find_and_delete_key(item, key)
        elif k == key:
            obj.pop(key, None)

def find_and_redact_key(obj: dict, key: str):
    """
    Given a dictionary, tries to find a (nested) key and redact its value
    """
    for k, v in obj.items():
        if isinstance(v, dict):
            find_and_redact_key(v, key)
        elif isinstance(v, list):
            for item in obj[k]:
                if isinstance(item, dict):
                    find_and_redact_key(item, key)
        elif k == key:
            obj[k] = '*****'
