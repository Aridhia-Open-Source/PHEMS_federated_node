from collections.abc import Callable
from functools import partial

import requests
import sqlalchemy as sa
from kubernetes.client.exceptions import ApiException
from sqlalchemy.orm import validates

from app.helpers.exceptions import GitProviderError, InvalidRequest
from app.helpers.git_tokens import mint_token
from app.helpers.git_uri import normalise_repo_path
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
    # The secret holding the git credential (see helpers/git_tokens.py). Set explicitly rather than
    # derived from the repository, so repositories can share one credential.
    secret_id = sa.Column(
        sa.Integer, sa.ForeignKey('secrets.id', ondelete='RESTRICT'), nullable=False
    )

    @validates('repo_path')
    def validate_repo_path(self, key, value):
        """Keep the repo_path in its normalised form (see normalise_repo_path)."""
        return normalise_repo_path(value)

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

    def check_connection(self) -> ConnectionCheck:
        return self.prepare_connection_check()()

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
        except GitProviderError as e:
            check = ConnectionCheck(ConnectionStatus.ERROR, e.description)
            return lambda: check
        except requests.RequestException as e:
            check = ConnectionCheck(ConnectionStatus.UNREACHABLE, type(e).__name__)
            return lambda: check

        url = f"{self.provider.api_uri.rstrip('/')}/{GitProviderType(self.provider.type).repo_api_path(self.repo_path)}"
        return partial(self._request_check, url, token)

    @staticmethod
    def _request_check(url: str, token: str) -> ConnectionCheck:
        return request_check(url, token)
