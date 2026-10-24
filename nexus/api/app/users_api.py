"""
STUB: not ported yet. Port webserver/app/users_api.py here, following nexus/api/HANDOVER.md "How to port a router".
"""
from fastapi import APIRouter

from app.helpers.keycloak import Keycloak  # noqa: F401  patched by tests/conftest.py

router = APIRouter()

