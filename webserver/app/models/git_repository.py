import time
import urllib.parse

import requests
import sqlalchemy as sa
from kubernetes.client.exceptions import ApiException
from sqlalchemy.orm import validates

from app.helpers.const import DEFAULT_NAMESPACE
from app.helpers.kubernetes import KubernetesClient
from app.models.git_provider import ConnectionCheck, ConnectionStatus, GitProvider


CONNECTION_TIMEOUT = 5
MAX_MESSAGE_LENGTH = 200


class GitRepositoryMixin:
    """
    What every repository the node reaches over a git host's API has: where it is, which
    provider serves it, and the secret holding its token. A model using it declares the
    composite foreign key to k8s_secrets (project_id, k8s_secret_id) and the k8s_secret
    relationship itself.
    """

    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )

    uri = sa.Column(sa.String(4096), nullable=False)
    provider = sa.Column(sa.String(16), nullable=False)
    # The scheme is stripped from uri, so the provider's API base URL is kept explicitly.
    api_uri = sa.Column(sa.String(4096), nullable=False)
    # Where the repository is on the provider's API (owner/repo). Stored rather than derived
    # from uri, which can carry a sub-path when the provider is installed under one.
    repo_path = sa.Column(sa.String(4096), nullable=False)
    # The secret holding the git token (under the key TOKEN). Set explicitly rather than
    # derived from uri, so repositories can share one credential. The composite foreign
    # key keeps it to a secret of this repository's own project.
    k8s_secret_id = sa.Column(sa.Integer, nullable=False)

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

    @property
    def k8s_secret_name(self) -> str:
        return self.k8s_secret.name

    @property
    def k8s_secret_k8s_name(self) -> str:
        return self.k8s_secret.k8s_name

    @classmethod
    def parse_repo_uri(cls, uri: str) -> str:
        """
        Parse the repository URI to extract the host and path.
        """
        parsed = urllib.parse.urlparse(uri)
        return (parsed.netloc + parsed.path).lower().rstrip('/')

    @classmethod
    def derive_repo_path(cls, uri: str) -> str:
        """
        The uri without its host, for when the repository is at the root of its provider.
        """
        return '/'.join(cls.parse_repo_uri(uri).split('/')[1:])

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

        url = f"{self.api_uri.rstrip('/')}/{GitProvider(self.provider).repo_api_path(self.repo_path)}"
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
