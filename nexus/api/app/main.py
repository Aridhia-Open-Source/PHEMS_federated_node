"""
A collection of general use endpoints
These won't have any restrictions and won't go through
    Keycloak for token validation.
"""
from http import HTTPStatus

import requests
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .dtos.healthcheck import NodeHealthDTO
from .helpers.exceptions import AuthenticationError, InvalidRequest
from .helpers.keycloak import URLS, Keycloak

router = APIRouter(tags=["main"])


@router.get('/', include_in_schema=False)
def index():
    """
    GET / endpoint.
        Redirects to /health_check
    """
    return RedirectResponse('/health_check', status_code=HTTPStatus.FOUND)


@router.get("/ready_check")
def ready_check() -> dict:
    """
    GET /ready_check endpoint
        Mostly to tell k8s the server has started
    """
    return {"status": "ready"}


@router.get(
    "/health_check", response_model=NodeHealthDTO, responses={HTTPStatus.BAD_GATEWAY: {"model": NodeHealthDTO}}
)
def health_check():
    """
    GET /health_check endpoint
        Checks the connection to keycloak and returns a jsonized summary
    """
    try:
        kc_request = requests.get(URLS["health_check"], timeout=30)
        kc_status = kc_request.ok
        status_text = "ok" if kc_request.ok else "non operational"
        code = HTTPStatus.OK if kc_request.ok else HTTPStatus.BAD_GATEWAY
    except requests.exceptions.ConnectionError:
        kc_status = False
        status_text = "non operational"
        code = HTTPStatus.BAD_GATEWAY

    return JSONResponse({"status": status_text, "keycloak": kc_status}, status_code=code)


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
