from abc import abstractmethod
from typing import Any, Union

from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext

from fednode.clients.git.gitea import GiteaClient
from fednode.clients.git.github import GitHubClient
from fednode.clients.git.provider import GitProvider
from fednode.clients.nexus.client import BackendAPI
from app.definitions.sensors.base import BaseSensor
from app.settings import settings
from fednode.clients.nexus.models import ResultsRepository, TriggerRepository


class GitAPIFactory:
    """
    Builds the api client for a repository from its provider's type and API URI and a short-lived token
    the backend mints for it, so every repository authenticates as itself. The token is asked for when the
    client is built: build it just before the calls that need it, not at the start of a long run.
    """

    def __init__(self, backend_api: BackendAPI):
        self.backend_api = backend_api

    def for_repository(self, repo: TriggerRepository | ResultsRepository, project_id: int | None = None) -> GitProvider:
        """The client for a repository. project_id names the project the work is for, None for the repository as a whole."""
        kind = "trigger" if isinstance(repo, TriggerRepository) else "results"
        token = self.backend_api.get_repository_token(kind, repo.id, project_id).token
        timeout = (settings.http.connect_timeout, settings.http.read_timeout)
        match repo.provider.type:
            case "github":
                return GitHubClient(repo.provider.api_uri, token, timeout=timeout)
            case "gitea":
                return GiteaClient(repo.provider.api_uri, token, timeout=timeout)
            case provider_type:
                raise ValueError(f"Unsupported git provider {provider_type!r} for repository {repo.uri}")


class GitSensor(BaseSensor):
    """Base class for the sensors that work against a git provider."""

    def __init__(
        self,
        context: Union[OpExecCtx, RunStatusSensorContext],
        backend_api: BackendAPI,
        git_apis: GitAPIFactory,
    ):
        super().__init__(context)
        self.backend_api = backend_api
        self.git_apis = git_apis

    @abstractmethod
    def __call__(self, *args: Any, **kwds: Any) -> Any:
        """GitSensor is abstract: the concrete git sensors implement this."""
