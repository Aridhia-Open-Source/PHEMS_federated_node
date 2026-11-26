"""
Getting and keeping a token. These need no token, so they are in OPEN_ROUTERS:
- POST /login
- POST /refresh_token
- PUT /global/users/reset-password, a new user swaps their temp password
"""
from http import HTTPStatus

from fastapi import APIRouter, Body, Depends, Form, Request

from app.helpers.exceptions import AuthenticationError, InvalidRequest
from app.clients.keycloak import Keycloak, user_tokens
from app.rules.authz import Access, Action

# Unchecked: getting a token, or a new user swapping their temporary password, before there is a caller
router = APIRouter(tags=["auth"], dependencies=[Depends(Access(action=Action.UNCHECKED))])


@router.post("/login")
def login(username: str | None = Form(None), password: str | None = Form(None)) -> dict:
    """
    POST /login endpoint.
        Given a form, logs the user in: {"token": <access token>, "refresh_token": ...}.
        Send the token as the Bearer; when it expires, swap the refresh token at /refresh_token.
    """
    if not username or not password:
        raise InvalidRequest("username and password are required")
    return user_tokens(grant_type="password", username=username, password=password)


@router.post("/refresh_token")
def refresh_token(request: Request) -> dict:
    """
    POST /refresh_token endpoint.
        Given the refresh token as the Bearer, returns a new pair, the same response as /login
    """
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token:
        raise AuthenticationError("Token not provided")
    return user_tokens(grant_type="refresh_token", refresh_token=token)


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
