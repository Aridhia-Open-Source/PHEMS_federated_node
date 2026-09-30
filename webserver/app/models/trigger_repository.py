import urllib.parse
from datetime import datetime as dt
from datetime import timezone as tz
from typing import cast

import time

import requests
import sqlalchemy as sa
from kubernetes.client.exceptions import ApiException
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.helpers.const import DEFAULT_NAMESPACE
from app.helpers.kubernetes import KubernetesClient
from app.models import Models, sqla_column
from app.models.git_provider import ConnectionCheck, ConnectionStatus, GitProvider


CONNECTION_TIMEOUT = 5
MAX_MESSAGE_LENGTH = 200


def now_ts():
    return dt.now(tz=tz.utc)


class TriggerRepository(db.Model, BaseModel):
    __tablename__ = 'trigger_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )

    uri = sa.Column(sa.String(4096), unique=True, nullable=False)
    provider = sa.Column(sa.String(16), nullable=False)
    # The scheme is stripped from uri, so the provider's API base URL is kept explicitly.
    api_uri = sa.Column(sa.String(4096), nullable=False)
    # The secret holding the git token (under the key TOKEN). Set explicitly rather than
    # derived from uri, so repositories can share one credential. The composite foreign
    # key below keeps it to a secret of this repository's own project.
    k8s_secret_id = sa.Column(sa.Integer, nullable=False)
    watch_dir = sa.Column(sa.String(4096), nullable=False)
    base_branch = sa.Column(sa.String(256), nullable=False, default='main')
    initial_cursor = sa.Column(
        sa.DateTime, nullable=False, server_default=func.now(), default=now_ts
    )

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ['project_id', 'k8s_secret_id'], ['k8s_secrets.project_id', 'k8s_secrets.id'],
            ondelete='RESTRICT'
        ),
    )

    project = relationship("Project", back_populates="trigger_repositories")
    k8s_secret = relationship(
        "K8sSecret", back_populates="trigger_repositories", overlaps="trigger_repositories,project"
    )
    pull_requests = relationship(
        "PullRequest", back_populates="trigger_repository", cascade="all, delete"
    )

    @validates('uri')
    def validate_uri(self, key, value):
        """Strip http/https schema from URI on save/update."""
        if value:
            value = self.parse_repo_uri(value)
        return value

    @validates('provider')
    def validate_provider(self, key, value):
        """Only providers the Dagster side has an API client for."""
        try:
            return GitProvider(value).value
        except ValueError:
            valid = ', '.join(p.value for p in GitProvider)
            raise ValueError(f"provider must be one of: {valid}")

    @validates('initial_cursor')
    def validate_initial_cursor(self, key, value):
        """Convert ISO 8601 string to datetime if needed."""
        if isinstance(value, str):
            try:
                value = dt.fromisoformat(value.rstrip('Z'))
            except (ValueError, TypeError):
                raise ValueError("initial_cursor must be a valid ISO 8601 datetime string")

        if self.id is not None and self.pull_requests:
            raise ValueError(
                "Cannot change initial_cursor while pull requests exist. "
                "Delete all pull requests first if you want to adjust the cursor."
            )

        return value

    @property
    def dataset(self):
        """
        Which dataset a PR from this repository runs against by default
        """
        return self.project.default_dataset

    @property
    def k8s_secret_name(self) -> str:
        return self.k8s_secret.name

    @property
    def k8s_secret_k8s_name(self) -> str:
        return self.k8s_secret.k8s_name

    @property
    def path(self):
        return '/'.join(self.uri.split('/')[1:])

    @classmethod
    def parse_repo_uri(cls, uri: str) -> str:
        """
        Parse the repository URI to extract the host and path.
        """
        parsed = urllib.parse.urlparse(uri)
        return (parsed.netloc + parsed.path).lower().rstrip('/')

    def get_token(self) -> str:
        """
        The git token, read from the cluster secret this repository names.
        """
        secret = KubernetesClient().read_namespaced_secret(self.k8s_secret_k8s_name, DEFAULT_NAMESPACE)
        if secret.data is None:
            raise KeyError("TOKEN")
        return KubernetesClient.decode_secret_value(secret.data['TOKEN'])

    def check_connection(self) -> ConnectionCheck:
        """
        Whether the repository can be reached with its token, the way the sensors reach it:
        through api_uri (not uri, which is the address people use), authenticating as a
        bearer token. Nothing returned includes the token.
        """
        try:
            token = self.get_token()
        except KeyError:
            return ConnectionCheck(
                ConnectionStatus.SECRET_MISSING, f"Secret {self.k8s_secret_name} has no TOKEN"
            )
        except ApiException as e:
            if e.status != 404:
                raise
            return ConnectionCheck(
                ConnectionStatus.SECRET_MISSING, f"Secret {self.k8s_secret_name} not found"
            )

        url = f"{self.api_uri.rstrip('/')}/repos/{self.path}"
        started = time.perf_counter()
        try:
            response = requests.get(
                url, headers={"Authorization": f"Bearer {token}"}, timeout=CONNECTION_TIMEOUT
            )
        except requests.RequestException as e:
            latency_ms = round((time.perf_counter() - started) * 1000)
            return ConnectionCheck(
                ConnectionStatus.UNREACHABLE, type(e).__name__, latency_ms=latency_ms
            )
        latency_ms = round((time.perf_counter() - started) * 1000)

        return ConnectionCheck(
            self._status_of(response.status_code, response.ok),
            self._message_of(response),
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _status_of(status_code: int, ok: bool) -> ConnectionStatus:
        if ok:
            return ConnectionStatus.OK
        if status_code in (401, 403):
            return ConnectionStatus.UNAUTHORIZED
        if status_code == 404:
            return ConnectionStatus.NOT_FOUND
        return ConnectionStatus.ERROR

    @staticmethod
    def _message_of(response) -> str:
        """The provider's own message on an error ("Bad credentials"), else the HTTP reason."""
        try:
            body = response.json()
        except ValueError:
            body = None
        message = body.get("message") if isinstance(body, dict) else None
        return str(message or response.reason)[:MAX_MESSAGE_LENGTH]

    def get_pull_request_cursor(self) -> str:
        """
        Get latest PR merge time from all ingested pull requests.
        If no pull requests exist, use initial_cursor as the starting point.
        """
        pr_cursor = db.session.query(func.max(Models.PullRequest.merged_at))\
            .filter_by(trigger_repository_id=self.id)\
            .scalar()

        initial_cursor = cast(dt, self.initial_cursor)

        return (pr_cursor or initial_cursor).strftime("%Y-%m-%dT%H:%M:%SZ")

    def __init__(
        self,
        uri: str,
        provider: str,
        api_uri: str,
        k8s_secret_id: int,
        watch_dir: str,
        project_id: int,
        base_branch: str = 'main',
        initial_cursor: dt | None = None,
    ):
        self.uri = uri
        self.provider = provider
        self.api_uri = api_uri
        self.k8s_secret_id = k8s_secret_id
        self.watch_dir = watch_dir
        self.project_id = project_id
        self.base_branch = base_branch
        self.initial_cursor = initial_cursor

    def __repr__(self):
        return f'<TriggerRepository ({self.uri})>'
