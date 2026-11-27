"""
Git helpers: the short-lived access token a git repository is used with (ADR 0023), and the directory paths inside
a repository. The repository's secret holds a long-lived credential, which the provider's git client
(fednode.clients.git.factory) exchanges for a token of about an hour, restricted to that repository and the
permission it needs: read for a trigger repository, write for a results repository. `mint_token` reads the secret
and keeps the cache; that a token may be handed out is checked by `GitRepositoryMixin.require_token_allowed`.

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

from app.helpers.exceptions import InvalidRequest
from app.clients.kubernetes import KubernetesClient

# The models import this module (GitRepositoryMixin.get_token), so they are only named in annotations
if TYPE_CHECKING:
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



def normalise_dir(directory: str) -> str:
    """
    Drops '.' and empty segments and the leading and trailing '/'. A '..' segment is refused,
    as it would let a directory point outside the one it is written under.
    """
    if not isinstance(directory, str):
        raise InvalidRequest("Directory must be a string")
    segments = [s for s in directory.split('/') if s not in ('', '.')]
    if '..' in segments:
        raise InvalidRequest(f"Directory '{directory}' must not contain '..'")
    return '/'.join(segments)


def dirs_overlap(a: str, b: str) -> bool:
    """Whether one directory is the other or inside it. An empty directory is the whole repository."""
    segments_a = [s for s in normalise_dir(a).split('/') if s]
    segments_b = [s for s in normalise_dir(b).split('/') if s]
    shorter = min(len(segments_a), len(segments_b))
    return segments_a[:shorter] == segments_b[:shorter]
