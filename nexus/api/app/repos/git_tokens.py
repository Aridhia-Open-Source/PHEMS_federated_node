"""
The short-lived access token a git repository is used with (ADR 0023). The repository's secret holds a long-lived
credential, which the provider's git client (fednode.clients.git.factory) exchanges for a token of about an hour,
restricted to that repository and the permission it needs: read for a trigger repository, write for a results
repository. This module reads the secret, keeps the cache and checks the token may be handed out.

A minted token is cached in the same secret, under CACHED_TOKEN_<repository id>_<permission> and the same with
_EXPIRES_AT, and reused while more than REUSE_MARGIN is left; a static TOKEN is never cached, so rotating the secret
reaches the next request. There is no lock: two requests that both find no valid cache both mint. Only the keys that
changed are written (KubernetesClient.patch_secret_data), so the credential survives and concurrent writes do not
conflict.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import TYPE_CHECKING

from fednode.clients.git import factory
from fednode.clients.git.provider import Permission

from app.helpers.exceptions import InvalidRequest, UnauthorizedError
from app.clients.kubernetes import KubernetesClient

# The models import this module (GitRepositoryMixin.get_token), so they are only named in annotations
if TYPE_CHECKING:
    from app.models.project_results_repository import ProjectResultsRepository
    from app.models.project_trigger_repository import ProjectTriggerRepository
    from app.models.results_repository import ResultsRepository
    from app.models.secret import Secret
    from app.models.trigger_repository import TriggerRepository

# A cached token with this much left or less is minted again
REUSE_MARGIN = timedelta(minutes=5)


def mint_token(
    secret: Secret, repository: TriggerRepository | ResultsRepository, permission: Permission
) -> tuple[str, datetime]:
    """
    A token for the repository with the permission, and when it expires (UTC). A cached token with more than
    REUSE_MARGIN left is returned as it is; otherwise one is minted and cached, with the provider's own changes
    to the secret in the same write. A secret with no credential for the repository's provider is a 409: the
    request is fine, the secret is not set up.
    """
    k8s = KubernetesClient()
    data = k8s.read_namespaced_secret(secret.key, secret.namespace).data or {}
    values = {key: KubernetesClient.decode_secret_value(value) for key, value in data.items()}
    provider = repository.provider
    try:
        cached = factory.credential_of(provider.type, values) != factory.STATIC_KEYS
    except factory.MissingCredential as e:
        raise InvalidRequest(f"Secret {secret.label} holds no git credential: {e}", HTTPStatus.CONFLICT) from e
    cache_key = f"CACHED_TOKEN_{repository.id}_{permission}"

    if cached and cache_key in values:
        expires_at = datetime.fromisoformat(values[f"{cache_key}_EXPIRES_AT"])
        if expires_at > datetime.now(tz=timezone.utc) + REUSE_MARGIN:
            return values[cache_key], expires_at

    minted = factory.mint_token(provider.type, provider.uri, provider.api_uri, repository.repo_path, values, permission)
    if cached:
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
