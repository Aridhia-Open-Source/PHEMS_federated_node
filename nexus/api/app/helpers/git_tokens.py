"""
The short-lived access token a git repository is used with (ADR 0023). The repository's secret holds a long-lived
credential, which the backend exchanges for a token of about an hour, restricted to that repository and the
permission it needs: read for a trigger repository, write for a results repository. Which keys the secret holds
picks the source: a GitHub App, a Gitea OAuth2 application or a static token.

A minted token is cached in the same secret, under CACHED_TOKEN_<repository id>_<permission> and the same with
_EXPIRES_AT, and reused while more than REUSE_MARGIN is left. There is no lock: two requests that both find no
valid cache both mint. Only the keys that changed are written (KubernetesClient.patch_secret_data), so the
credential survives and concurrent writes do not conflict.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import TYPE_CHECKING, Literal

import jwt
import requests

from app.helpers.exceptions import GitProviderError, InvalidRequest, UnauthorizedError
from app.helpers.kubernetes import KubernetesClient
from app.models.git_provider import _message_of

# The models import this module (GitRepositoryMixin.get_token), so they are only named in annotations
if TYPE_CHECKING:
    from app.models.project_results_repository import ProjectResultsRepository
    from app.models.project_trigger_repository import ProjectTriggerRepository
    from app.models.results_repository import ResultsRepository
    from app.models.secret import Secret
    from app.models.trigger_repository import TriggerRepository

Permission = Literal["read", "write"]

REQUEST_TIMEOUT = 10
# GitHub takes an App JWT of at most 10 minutes; issued a minute in the past for clock drift
JWT_LIFETIME = timedelta(minutes=9)
JWT_BACKDATE = timedelta(seconds=60)
# A cached token with this much left or less is minted again
REUSE_MARGIN = timedelta(minutes=5)
# A static token does not expire; its expires_at says an hour so that callers ask again, as they do for a minted one
STATIC_LIFETIME = timedelta(hours=1)


@dataclass
class MintedToken:
    token: str
    expires_at: datetime
    # Keys the source wants written to the secret with the token (Gitea's new refresh token)
    secret_updates: dict[str, str] = field(default_factory=dict)


def _post(url: str, **kwargs) -> dict:
    """
    POST and the JSON answer. A failure is a 502 with the provider's own message; the request holds credentials,
    so it is not in it.
    """
    response = requests.post(url, timeout=REQUEST_TIMEOUT, **kwargs)
    if not response.ok:
        raise GitProviderError(f"{url} answered {response.status_code}: {_message_of(response)}")
    return response.json()


class GithubAppSource:
    """An installation token of the GitHub App, restricted to the repository and permission, with GitHub's expiry."""
    KEYS = frozenset({"APP_ID", "INSTALLATION_ID", "PRIVATE_KEY"})
    CACHED = True

    @staticmethod
    def mint(
        values: dict[str, str], repository: TriggerRepository | ResultsRepository, permission: Permission
    ) -> MintedToken:
        now = datetime.now(tz=timezone.utc)
        app_jwt = jwt.encode(
            {"iss": values["APP_ID"], "iat": now - JWT_BACKDATE, "exp": now + JWT_LIFETIME},
            values["PRIVATE_KEY"],
            algorithm="RS256",
        )
        body = _post(
            f"{repository.provider.api_uri.rstrip('/')}/app/installations/{values['INSTALLATION_ID']}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
            # GitHub takes the repository's name, not owner/name
            json={
                "repositories": [repository.repo_path.split("/")[1]],
                "permissions": {"contents": permission, "pull_requests": permission},
            },
        )
        return MintedToken(body["token"], datetime.fromisoformat(body["expires_at"]))


class GiteaOAuthSource:
    """
    An OAuth2 access token of the Gitea application, from its refresh token, which the answer replaces. The token acts
    as the user who authorised the application: Gitea cannot restrict it to one repository or permission.
    """
    KEYS = frozenset({"CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"})
    CACHED = True

    @staticmethod
    def mint(
        values: dict[str, str], repository: TriggerRepository | ResultsRepository, permission: Permission
    ) -> MintedToken:
        now = datetime.now(tz=timezone.utc)
        body = _post(
            f"{repository.provider.uri}/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "grant_type": "refresh_token",
                "client_id": values["CLIENT_ID"],
                "client_secret": values["CLIENT_SECRET"],
                "refresh_token": values["REFRESH_TOKEN"],
            },
        )
        return MintedToken(
            body["access_token"], now + timedelta(seconds=body["expires_in"]), {"REFRESH_TOKEN": body["refresh_token"]}
        )


class StaticSource:
    """The secret's TOKEN as it is. Never cached, so rotating the secret reaches the next request."""
    KEYS = frozenset({"TOKEN"})
    CACHED = False

    @staticmethod
    def mint(
        values: dict[str, str], repository: TriggerRepository | ResultsRepository, permission: Permission
    ) -> MintedToken:
        return MintedToken(values["TOKEN"], datetime.now(tz=timezone.utc) + STATIC_LIFETIME)


# In this order: a secret that still holds a TOKEN beside the App or OAuth2 keys uses them
SOURCES = (GithubAppSource, GiteaOAuthSource, StaticSource)


def missing_credential_keys(keys: Iterable[str]) -> set[str]:
    """
    What a secret holding these keys lacks of the nearest complete credential (the one with the fewest keys
    missing, the first of SOURCES on a tie). Empty when it holds one.
    """
    return min((source.KEYS - set(keys) for source in SOURCES), key=len)


def pick_source(secret: Secret, values: dict[str, str]):
    """The first source whose keys the secret holds. A 409: the request is fine, the secret is not set up."""
    for source in SOURCES:
        if source.KEYS <= values.keys():
            return source
    raise InvalidRequest(
        f"Secret {secret.label} holds no git credential: it needs APP_ID, INSTALLATION_ID and PRIVATE_KEY, "
        "or CLIENT_ID, CLIENT_SECRET and REFRESH_TOKEN, or TOKEN",
        HTTPStatus.CONFLICT,
    )


def mint_token(
    secret: Secret, repository: TriggerRepository | ResultsRepository, permission: Permission
) -> tuple[str, datetime]:
    """
    A token for the repository with the permission, and when it expires (UTC). A cached token with more than
    REUSE_MARGIN left is returned as it is; otherwise one is minted and cached, with the source's own changes
    to the secret in the same write.
    """
    k8s = KubernetesClient()
    data = k8s.read_namespaced_secret(secret.key, secret.namespace).data or {}
    values = {key: KubernetesClient.decode_secret_value(value) for key, value in data.items()}
    source = pick_source(secret, values)
    cache_key = f"CACHED_TOKEN_{repository.id}_{permission}"

    if source.CACHED and cache_key in values:
        expires_at = datetime.fromisoformat(values[f"{cache_key}_EXPIRES_AT"])
        if expires_at > datetime.now(tz=timezone.utc) + REUSE_MARGIN:
            return values[cache_key], expires_at

    minted = source.mint(values, repository, permission)
    if source.CACHED:
        k8s.patch_secret_data(secret.key, secret.namespace, {
            cache_key: minted.token,
            f"{cache_key}_EXPIRES_AT": minted.expires_at.isoformat(),
            **minted.secret_updates,
        })
    return minted.token, minted.expires_at


def require_token_allowed(
    repository: TriggerRepository | ResultsRepository,
    project_id: int | None,
    assignment: ProjectTriggerRepository | ProjectResultsRepository | None,
) -> None:
    """
    A 403 unless a token may be handed out for the repository: it, its provider and its secret are on and not
    revoked and, when project_id names a project, the project and its resource for the repository are not revoked
    (ADR 0008). Switched off is not revoked: a disabled project or resource still gets a token, as its finished
    results are delivered. The assignment is that resource found with deleted ones included (a deleted one is
    revoked), None when the project has none. Checked before the cache is read, so a cached token is refused too.
    """
    if not repository.active:
        raise UnauthorizedError(f"Repository {repository.uri} is disabled or revoked")
    secret = repository.secret
    if not secret.enabled or secret.deleted_at is not None:
        raise UnauthorizedError(f"Secret {secret.label} is disabled or deleted")
    if project_id is None:
        return
    if assignment is None:
        raise UnauthorizedError(f"Repository {repository.uri} is not assigned to project {project_id}")
    if assignment.project.revoked:
        raise UnauthorizedError(f"Project {project_id} is revoked")
    if assignment.revoked:
        raise UnauthorizedError(f"Repository {repository.uri} is revoked for project {project_id}")
