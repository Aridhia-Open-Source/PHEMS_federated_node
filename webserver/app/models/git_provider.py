"""A git host the node's repositories live on, and what checking a connection to one finds."""
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import partial

import requests
import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.helpers.git_uri import normalise_provider_uri, validate_api_uri
from app.helpers.soft_delete import SoftDeleteMixin
from app.models import sqla_column
from app.models.git_provider_type import GitProviderType

CONNECTION_TIMEOUT = 5
MAX_MESSAGE_LENGTH = 200


class ConnectionStatus(str, Enum):
    """The outcome of checking that a trigger repository can be reached with its token."""

    OK = "ok"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    UNREACHABLE = "unreachable"
    SECRET_MISSING = "secret_missing"
    ERROR = "error"

    def __str__(self):
        return self.value


@dataclass
class ConnectionCheck:
    """
    What checking a trigger repository's connection found. The status code and latency are
    only known when a request was made.
    """

    status: ConnectionStatus
    message: str
    status_code: int | None = None
    latency_ms: int | None = None


def request_check(url: str, token: str | None = None) -> ConnectionCheck:
    """GET the url, with the token as a bearer token if there is one, and report what came back."""
    started = time.perf_counter()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = requests.get(url, headers=headers, timeout=CONNECTION_TIMEOUT)
    except requests.RequestException as e:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return ConnectionCheck(
            ConnectionStatus.UNREACHABLE, type(e).__name__, latency_ms=latency_ms
        )
    latency_ms = round((time.perf_counter() - started) * 1000)

    return ConnectionCheck(
        _status_of(response.status_code, response.ok),
        _message_of(response),
        status_code=response.status_code,
        latency_ms=latency_ms,
    )


def _status_of(status_code: int, ok: bool) -> ConnectionStatus:
    if ok:
        return ConnectionStatus.OK
    if status_code in (401, 403):
        return ConnectionStatus.UNAUTHORIZED
    if status_code == 404:
        return ConnectionStatus.NOT_FOUND
    return ConnectionStatus.ERROR


def _message_of(response) -> str:
    """The provider's own message on an error ("Bad credentials"), else the HTTP reason."""
    try:
        body = response.json()
    except ValueError:
        body = None
    message = body.get("message") if isinstance(body, dict) else None
    return str(message or response.reason)[:MAX_MESSAGE_LENGTH]


class GitProvider(SoftDeleteMixin, db.Model, BaseModel):
    """
    A git host, global: the trigger and results repositories on it refer to it. The uri is
    the host's web address (https://github.com) and the api_uri its API base URL, which the
    repositories' tokens are sent to.
    """
    __tablename__ = 'git_providers'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    name = sa.Column(sa.String(253), nullable=False)
    type = sa.Column(sa.String(16), nullable=False)
    uri = sa.Column(sa.String(4096), nullable=False)
    api_uri = sa.Column(sa.String(4096), nullable=False)
    # Turned on or off for the whole node: the repositories on a disabled provider are not active
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.Index('uq_git_providers_name', 'name', unique=True, postgresql_where=sa.text('deleted_at IS NULL')),
        sa.Index('uq_git_providers_uri', 'uri', unique=True, postgresql_where=sa.text('deleted_at IS NULL')),
    )

    trigger_repositories = relationship("TriggerRepository", back_populates="provider")
    results_repositories = relationship("ResultsRepository", back_populates="provider")

    @classmethod
    def get_by_request_id(cls, provider_id: int) -> "GitProvider":
        """For the requests that reference a provider by id, so a missing one is a 400."""
        provider = cls.query.filter(cls.id == provider_id).one_or_none()
        if provider is None:
            raise InvalidRequest(f"Git provider {provider_id} does not exist")
        return provider

    @validates('type')
    def validate_type(self, key, value):
        """Only types the Dagster side has an API client for."""
        try:
            return GitProviderType(value).value
        except ValueError:
            valid = ', '.join(t.value for t in GitProviderType)
            raise ValueError(f"type must be one of: {valid}")

    @validates('uri')
    def validate_uri(self, key, value):
        """Keep the uri in its normalised form (see normalise_provider_uri)."""
        return normalise_provider_uri(value)

    @validates('api_uri')
    def check_api_uri(self, key, value):
        """Keep the api_uri on the provider's host (see validate_api_uri). Set after uri."""
        return validate_api_uri(value, self.uri)

    def prepare_connection_check(self) -> Callable[[], ConnectionCheck]:
        """
        Whether the provider's API answers, without a token. Returns the network call to
        make later, which touches nothing else so it can run in a thread.
        """
        url = f"{self.api_uri.rstrip('/')}/{GitProviderType(self.type).health_api_path}"
        return partial(request_check, url)

    def __init__(
        self,
        name: str,
        type: str,
        uri: str,
        api_uri: str,
        enabled: bool = True,
    ):
        self.name = name
        self.type = type
        self.uri = uri
        self.api_uri = api_uri
        self.enabled = enabled

    def __repr__(self):
        return f'<GitProvider ({self.name})>'
