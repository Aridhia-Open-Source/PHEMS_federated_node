"""Git hosting provider types."""

from enum import Enum


class GitProviderType(str, Enum):
    """
    Which kind of git host a provider is, so the sensors know which API client to build.
    Each value is a type the Dagster side has an API client for.
    """

    GITHUB = "github"
    GITEA = "gitea"

    def __str__(self):
        return self.value

    def repo_api_path(self, repo_path: str) -> str:
        """The path, under the provider's API base URL, of the repository itself."""
        return f"repos/{repo_path}"

    @property
    def health_api_path(self) -> str:
        """A path, under the provider's API base URL, that answers without a token."""
        return "version" if self is GitProviderType.GITEA else ""
