from abc import abstractmethod
from typing import Any, Protocol, Union

from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext

from app.backend import BackendAPI
from app.definitions.sensors.base import BaseSensor
from app.gitea import GiteaAPI, GiteaClient
from app.github import GithubAPI, GithubClient
from app.models import ResultsRepository, TriggerRepository


class GitAPI(Protocol):
    """Protocol required for a git provider api client (i.e Gitea, GitHub, GitLab)"""

    def get_pull_request(self, repo_path: str, pr_number: int) -> dict: ...

    def get_new_merged_pulls(self, repo_path: str, merged_after: str) -> list[dict]: ...

    def get_pull_request_files(self, repo_path: str, pr_number: int) -> list[dict]: ...

    def get_file_contents(self, repo_path: str, file_path: str, ref: str) -> str: ...

    def get_default_branch(self, repo_path: str) -> str: ...

    def find_pull_request_by_branch(self, repo_path: str, head_branch: str, base_branch: str) -> dict | None: ...

    def create_pull_request(
        self, repo_path: str, head_branch: str, base_branch: str, title: str, body: str
    ) -> dict: ...


class GitAPIFactory:
    """
    Builds the api client for a repository from its provider's type and API URI and a short-lived token
    the backend mints for it, so every repository authenticates as itself. The token is asked for when the
    client is built: build it just before the calls that need it, not at the start of a long run.
    """

    def __init__(self, backend_api: BackendAPI):
        self.backend_api = backend_api

    def for_repository(self, repo: TriggerRepository | ResultsRepository, project_id: int | None = None) -> GitAPI:
        """The client for a repository. project_id names the project the work is for, None for the repository as a whole."""
        kind = "trigger" if isinstance(repo, TriggerRepository) else "results"
        token = self.backend_api.get_repository_token(kind, repo.id, project_id).token
        match repo.provider.type:
            case "github":
                return GithubAPI(GithubClient(token=token, base_uri=repo.provider.api_uri))
            case "gitea":
                return GiteaAPI(GiteaClient(token=token, base_uri=repo.provider.api_uri))
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
