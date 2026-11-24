"""
A collection of general use endpoints
These won't have any restrictions and won't go through
    Keycloak for token validation.
"""
from http import HTTPStatus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.dtos.healthcheck import NodeHealthDTO
from app.rules.authz import Access, Action
from app.helpers.exceptions import AuthenticationError, InvalidRequest
from app.clients.keycloak import KEYCLOAK_HTTP, URLS, user_tokens
from app.clients.outbound import OutboundError, ttl_cache

# Unchecked: probes and getting a token, before there is a caller
router = APIRouter(tags=["main"], dependencies=[Depends(Access(action=Action.UNCHECKED))])

# /health_check is open to anyone: a short timeout and one Keycloak call per window keep a flood off Keycloak
HEALTH_CHECK_TIMEOUT = (2, 3)
HEALTH_CHECK_CACHE_SECONDS = 5


@ttl_cache(HEALTH_CHECK_CACHE_SECONDS)
def keycloak_is_up() -> bool:
    """Whether Keycloak answers, asked at most once per HEALTH_CHECK_CACHE_SECONDS."""
    return KEYCLOAK_HTTP.get(URLS["health_check"], timeout=HEALTH_CHECK_TIMEOUT).ok


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
        kc_status = keycloak_is_up()
    except OutboundError:
        kc_status = False
    status_text = "ok" if kc_status else "non operational"
    code = HTTPStatus.OK if kc_status else HTTPStatus.BAD_GATEWAY

    return JSONResponse({"status": status_text, "keycloak": kc_status}, status_code=code)


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
