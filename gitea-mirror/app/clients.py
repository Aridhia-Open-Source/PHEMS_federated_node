from typing import Protocol


class UserSyncError(Exception):
    """A client failed while listing or creating users."""


class GithubClient(Protocol):
    """Implemented by stage m3 (real HTTP client)."""

    def list_users(self, upstream_uri: str, secret_namespace: str, secret_key: str) -> list[str]:
        """GitHub logins of the repository's contributors and collaborators."""
        ...


class GiteaClient(Protocol):
    """Implemented by stage m4 (real HTTP client)."""

    def ensure_user(self, login: str) -> bool:
        """Create the shadow user if missing. True if created, False if it existed."""
        ...


class UnconfiguredGithubClient:
    def list_users(self, upstream_uri, secret_namespace, secret_key):
        raise NotImplementedError('GitHub client not available until stage m3')


class UnconfiguredGiteaClient:
    def ensure_user(self, login):
        raise NotImplementedError('Gitea client not available until stage m4')
