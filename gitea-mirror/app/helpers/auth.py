import hmac
from flask import request
from app.helpers.errors import Unauthorized

OPEN_ENDPOINTS = {'main.health'}


def require_api_token(value) -> str:
    """The configured token, or RuntimeError if it is empty: the service must not start open."""
    if value is None or not value.strip():
        raise RuntimeError('GITEA_MIRROR_API_TOKEN must not be empty')
    return value


def check_bearer_token(expected: str):
    if request.endpoint in OPEN_ENDPOINTS:
        return
    if not expected:  # never accept `Bearer ` against an empty secret
        raise Unauthorized()
    header = request.headers.get('Authorization', '')
    scheme, _, token = header.partition(' ')
    # Compare bytes: compare_digest(str, str) raises TypeError on non-ASCII input (a 500, not a 401).
    supplied = token.encode('utf-8', 'surrogateescape')
    if scheme != 'Bearer' or not token or not hmac.compare_digest(supplied, expected.encode()):
        raise Unauthorized()
