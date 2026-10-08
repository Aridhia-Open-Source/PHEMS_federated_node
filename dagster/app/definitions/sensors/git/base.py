from typing import Protocol, Union

from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext

from app.backend import BackendAPI
from app.definitions.sensors.base import BaseSensor
from app.gitea import GiteaAPI, GiteaClient
from app.github import GithubAPI, GithubClient
from app.models import ResultsRepository, TriggerRepository
from app.secrets import SecretProvider


class GitAPI(Protocol):
    """Protocol required for a git provider api client (i.e Gitea, GitHub, GitLab)"""

    def get_pull_request(self, repo_path: str, pr_number: int) -> dict: ...

    def get_new_merged_pulls(self, repo_path: str, base_branch: str, merged_after: str) -> list[dict]: ...

    def get_pull_request_files(self, repo_path: str, pr_number: int) -> list[dict]: ...

    def get_file_contents(self, repo_path: str, file_path: str, ref: str) -> str: ...

    def find_pull_request_by_branch(self, repo_path: str, head_branch: str, base_branch: str) -> dict | None: ...

    def create_pull_request(
        self, repo_path: str, head_branch: str, base_branch: str, title: str, body: str
    ) -> dict: ...


class GitAPIFactory:
    """
    Builds the api client for a repository from its provider, its API URI and the token in
    the secret it names, so every repository authenticates as itself.
    """

    def for_repository(self, repo: TriggerRepository | ResultsRepository) -> GitAPI:
        token = SecretProvider(repo.secret.provider).get(repo.secret.key, repo.secret.namespace, "TOKEN")
        match repo.provider:
            case "github":
                return GithubAPI(GithubClient(token=token, base_uri=repo.api_uri))
            case "gitea":
                return GiteaAPI(GiteaClient(token=token, base_uri=repo.api_uri))
            case provider:
                raise ValueError(f"Unsupported git provider {provider!r} for repository {repo.uri}")


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
