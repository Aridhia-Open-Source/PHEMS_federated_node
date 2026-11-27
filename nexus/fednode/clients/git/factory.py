"""
Which client serves a git provider, and the short-lived token a repository's credential gives (ADR 0023). Dagster
and the API build git clients and mint tokens here, so both pick the same client for a provider type.

A repository's secret holds its provider's own credential (the client's CREDENTIAL_KEYS: a GitHub App or a Gitea
OAuth2 application), which is exchanged for a token, or a static TOKEN, used as it is. The provider's own
credential wins over a TOKEN left beside it.
"""
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from fednode.clients.git.gitea import GiteaClient
from fednode.clients.git.github import GitHubClient
from fednode.clients.git.provider import GitProvider, MintedToken, Permission

CLIENTS: dict[str, type[GitProvider]] = {"github": GitHubClient, "gitea": GiteaClient}
STATIC_KEYS = frozenset({"TOKEN"})
# A static token does not expire; its expires_at says an hour so that callers ask again, as they do for a minted one
STATIC_LIFETIME = timedelta(hours=1)


class MissingCredential(Exception):
    """A secret holds neither its provider's own credential nor a TOKEN."""


def client_class(provider_type: str) -> type[GitProvider]:
    if provider_type not in CLIENTS:
        raise ValueError(f"Unsupported git provider {provider_type!r}")
    return CLIENTS[provider_type]


def build_client(provider_type: str, api_uri: str, token: str) -> GitProvider:
    """The API client of a provider of this type, authenticated with the token."""
    return client_class(provider_type)(api_uri, token)


def credential_of(provider_type: str, keys: Iterable[str]) -> frozenset[str]:
    """The keys of the credential a secret holding these keys gives a provider of this type."""
    for credential in (client_class(provider_type).CREDENTIAL_KEYS, STATIC_KEYS):
        if credential <= set(keys):
            return credential
    raise MissingCredential(
        "it needs APP_ID, INSTALLATION_ID and PRIVATE_KEY, or CLIENT_ID, CLIENT_SECRET and REFRESH_TOKEN, or TOKEN"
    )


def missing_credential_keys(keys: Iterable[str]) -> set[str]:
    """
    What a secret holding these keys lacks of the nearest complete credential of any provider (the one with the
    fewest keys missing, GitHub's first on a tie, a TOKEN last). Empty when it holds one.
    """
    credentials = (*(client.CREDENTIAL_KEYS for client in CLIENTS.values()), STATIC_KEYS)
    return min((credential - set(keys) for credential in credentials), key=len)


def mint_token(
    provider_type: str, uri: str, api_uri: str, repo_path: str, credentials: dict[str, str], permission: Permission
) -> MintedToken:
    """A token for the repository with the permission, from the credential in its secret's values."""
    if credential_of(provider_type, credentials) == STATIC_KEYS:
        return MintedToken(credentials["TOKEN"], datetime.now(tz=timezone.utc) + STATIC_LIFETIME)
    return client_class(provider_type).mint_token(uri, api_uri, repo_path, credentials, permission)
