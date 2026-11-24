"""
Getting and keeping a token. These need no token, so they are in OPEN_ROUTERS:
- POST /login
- POST /refresh_token
- PUT /global/users/reset-password, a new user swaps their temp password
"""
from http import HTTPStatus

from fastapi import APIRouter, Body, Form, Request

from app.helpers.exceptions import AuthenticationError, InvalidRequest
from app.clients.keycloak import Keycloak

router = APIRouter(tags=["auth"])


@router.post("/login")
def login(username: str | None = Form(None), password: str | None = Form(None)) -> dict:
    """
    POST /login endpoint.
        Given a form, logs the user in, returning a refresh_token from Keycloak
    """
    if not username or not password:
        raise InvalidRequest("username and password are required")
    return {"token": Keycloak().get_token(username=username, password=password)}


@router.post("/refresh_token")
def refresh_token(request: Request) -> dict:
    """
    POST /refresh_token endpoint.
        Given a token, exchanges it for a new one. Returns the same
        response as /login
    """
    token = Keycloak.get_token_from_headers(request.headers)
    kc_client = Keycloak()
    if not kc_client.is_token_valid(token, resource=None, scope=None, with_permissions=False):
        raise AuthenticationError()

    return {"token": kc_client.exchange_global_token(token, "refresh_token")}


@router.put('/global/users/reset-password', status_code=HTTPStatus.NO_CONTENT)
def reset_password(body: dict = Body(default_factory=dict)):
    """
    PUT /global/users/reset-password endpoint. Interface to keycloak
        API, so we can change the credentials and make sure
        there are no pending action to undertake
    """
    kc = Keycloak()
    user = kc.get_user_by_email(email=body.get("email"))
    kc.reset_user_pass(
        user_id=user["id"], username=user["username"],
        old_pass=body.get("tempPassword"),
        new_pass=body.get("newPassword")
    )
