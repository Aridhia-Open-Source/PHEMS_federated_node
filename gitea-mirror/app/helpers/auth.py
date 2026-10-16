import hmac
from flask import request
from app.helpers.errors import Unauthorized

OPEN_ENDPOINTS = {'main.health'}


def check_bearer_token(expected: str):
    if request.endpoint in OPEN_ENDPOINTS:
        return
    header = request.headers.get('Authorization', '')
    scheme, _, token = header.partition(' ')
    if scheme != 'Bearer' or not hmac.compare_digest(token, expected):
        raise Unauthorized()
