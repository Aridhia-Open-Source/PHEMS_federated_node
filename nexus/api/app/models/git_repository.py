from collections.abc import Callable
from functools import partial

import requests
import sqlalchemy as sa
from kubernetes.client.exceptions import ApiException

from app.helpers.exceptions import InvalidRequest, UnauthorizedError
from app.helpers.git import mint_token
from fednode.http import ClientError
from app.models.git_provider import ConnectionCheck, ConnectionStatus, request_check
from app.models.git_provider_type import GitProviderType


class GitRepositoryMixin:
    """
    What every repository the node reaches over a git host's API has: where it is, which
    provider serves it, and the secret holding its token. A model using it declares the
    secret relationship itself.
    """

    provider_id = sa.Column(
        sa.Integer, sa.ForeignKey('git_providers.id', ondelete='RESTRICT'), nullable=False
    )
    # Where the repository is on the provider (owner/name)
    repo_path = sa.Column(sa.String(512), nullable=False)
    # The secret holding the git credential (see helpers/git.py). Set explicitly rather than
    # derived from the repository, so repositories can share one credential.
    secret_id = sa.Column(
        sa.Integer, sa.ForeignKey('secrets.id', ondelete='RESTRICT'), nullable=False
    )

    @property
    def uri(self) -> str:
        """The repository's address: the provider's uri and the repo_path."""
        return f"{self.provider.uri}/{self.repo_path}"

    @property
    def active(self) -> bool:
        """Whether the repository is turned on and not revoked, and so is its provider."""
        return self.enabled and not self.revoked and self.provider.enabled and not self.provider.revoked

    def get_token(self) -> str:
        """
        A token with the repository's TOKEN_PERMISSION, minted (or cached) from the credential in the cluster
        secret this repository names. The same token the token routes hand out.
        """
        return mint_token(self.secret, self, self.TOKEN_PERMISSION)[0]

    def require_token_allowed(self, project_id: int | None, assignment) -> None:
        """
        A 403 unless a token may be handed out for the repository: it, its provider and its secret are on and not
        revoked and, when project_id names a project, the project and its resource for the repository are not revoked
        (ADR 0008). Switched off is not revoked: a disabled project or resource still gets a token, as its finished
        results are delivered. The assignment is that resource found with deleted ones included (a deleted one is
        revoked), None when the project has none. Checked before the cache is read, so a cached token is refused too.
        """
        if not self.active:
            raise UnauthorizedError(f"Repository {self.uri} is disabled or revoked")
        if not self.secret.enabled or self.secret.deleted_at is not None:
            raise UnauthorizedError(f"Secret {self.secret.label} is disabled or deleted")
        if project_id is None:
            return
        if assignment is None:
            raise UnauthorizedError(f"Repository {self.uri} is not assigned to project {project_id}")
        assignment.require_token_allowed()

    def prepare_connection_check(self) -> Callable[[], ConnectionCheck]:
        """
        Whether the repository can be reached with its token, the way the sensors reach it:
        through the provider's api_uri (not the uri, which is the address people use), authenticating as a
        bearer token. Nothing returned includes the token.

        Gets the token (the database, the cluster and, for a token not cached, the provider) now, and returns the
        network call to make later, which touches none of them so it can run in a thread. A token that cannot be
        got is reported as the check's result, not raised.
        """
        try:
            token = self.get_token()
        except InvalidRequest as e:
            # The secret holds no complete credential
            check = ConnectionCheck(ConnectionStatus.SECRET_MISSING, e.description)
            return lambda: check
        except ApiException as e:
            if e.status != 404:
                raise
            check = ConnectionCheck(
                ConnectionStatus.SECRET_MISSING, f"Secret {self.secret.label} not found"
            )
            return lambda: check
        except ClientError as e:
            check = ConnectionCheck(ConnectionStatus.ERROR, str(e))
            return lambda: check
        except requests.RequestException as e:
            check = ConnectionCheck(ConnectionStatus.UNREACHABLE, type(e).__name__)
            return lambda: check

        url = f"{self.provider.api_uri.rstrip('/')}/{GitProviderType(self.provider.type).repo_api_path(self.repo_path)}"
        return partial(self._request_check, url, token)

    @staticmethod
    def _request_check(url: str, token: str) -> ConnectionCheck:
        return request_check(url, token)
