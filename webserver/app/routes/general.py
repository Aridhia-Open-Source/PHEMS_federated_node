"""
A collection of general use endpoints
These won't have any restrictions and won't go through
    Keycloak for token validation.
"""
from http import HTTPStatus
from typing import Annotated, Literal
import httpx
import requests
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import APIRouter, Request as request, Form
from app.helpers.keycloak import Keycloak, URLS
from app.helpers.exceptions import AuthenticationError


router = APIRouter(tags=["general"])


@router.get('/')
async def index() -> RedirectResponse:
    """
    GET / endpoint.
        Redirects to /health_check
    """
    return RedirectResponse(url='health_check')

@router.get('/ready_check')
async def ready_check() -> dict[str, str]:
    """
    GET /ready_check endpoint
        Mostly to tell k8s Flask has started
    """
    return {"status": "ready"}

@router.get('/health_check')
async def health_check() -> JSONResponse:
    """
    GET /health_check endpoint
        Checks the connection to keycloak and returns a jsonized summary
    """
    try:
        async with httpx.AsyncClient() as requests:
            kc_request: httpx.Response = await requests.get(URLS["health_check"], timeout=30)
        kc_status: bool = kc_request.is_success
        status_text: Literal['ok'] | Literal['non operational'] = "ok" if kc_request.is_success else "non operational"
        code: HTTPStatus | HTTPStatus = HTTPStatus.OK if kc_request.is_success else HTTPStatus.BAD_GATEWAY
    except httpx.ConnectError:
        kc_status = False
        status_text = "non operational"
        code = HTTPStatus.BAD_GATEWAY

    return JSONResponse(
        content={
            "status": status_text,
            "keycloak": kc_status
        },
        status_code=code
    )

@router.post('/login')
async def login(username: Annotated[str, Form()], password: Annotated[str, Form()]) -> dict[str, str]:
    """
    POST /login endpoint.
        Given a form, logs the user in, returning a refresh_token from Keycloak
    """
    kc: Keycloak = await Keycloak.create()
    return {
        "token": await kc.get_token(**{"username": username, "password": password})
    }

@router.post('/refresh_token')
async def refresh_token(request: request) -> dict[str, str]:
    """
    POST /refresh_token endpoint.
        Given a token, exchanges it for a new one. Returns the same
        response as /login
    """
    token = await Keycloak.get_token_from_headers(request)
    kc_client: Keycloak = await Keycloak.create()
    if not await kc_client.is_token_valid(token, resource=None, scope=None, with_permissions=False):
        raise AuthenticationError()

    return {
        "token": await kc_client.exchange_global_token(token, "refresh_token")
    }
