"""
Config and helpers shared by the commands: what the env holds, and the Gitea and backend
APIs built from it.
"""

import subprocess
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlparse

import click
from pydantic import Field

from fncli.backend import FncliBackendAPI
from app.config import EnvConfig
from app.definitions.sensors.git.base import GitAPIFactory
from app.git_uri import normalise_repo_uri
from app.gitea import GiteaAPI
from app.github import GH_API_BASE_URL, GithubAPI, GithubClient
from app.models import ResultsRepository, TriggerRepository
from fncli.gitea import GiteaAdminAPI, GiteaAdminClient, GiteaWebClient
from fncli.k8s import get_k8s_secret
from fncli.nodefile.schema import NodeSpec
from app.utils import BackendAdapter, BackendSession

IN_CLUSTER_SUFFIX = "fn.svc"


def to_host_url(url: str) -> str:
    """
    The URL as this host-side script reaches it. An in-cluster host (gitea.fn.svc) is only
    reachable from the host through the Tilt port-forward on localhost, on the same port, so
    only the hostname changes. Any other URL is returned as it is.
    """
    host = urlparse(url).hostname
    if not host or not host.endswith(IN_CLUSTER_SUFFIX):
        return url
    return url.replace(host, "localhost", 1)


def find_under(directory: str, value: Path, hint: str = "") -> Path:
    """The path as given, else the same path under the nearest `directory`/ from here up (bootstrap/, triggers/)"""
    if value.is_file():
        return value
    for parent in (Path.cwd(), *Path.cwd().parents):
        candidate = parent / directory / value
        if candidate.is_file():
            return candidate
    raise click.BadParameter(f"{value} not found, as given or under {directory}/ from here up{hint}")


class BackendConfig(EnvConfig):
    """What reaches the node: the context's node (bootstrap/context.yaml), never the env"""

    node: NodeSpec


class NamespaceConfig(EnvConfig):
    """The release namespace, a deploy setting that stays in .dev.env"""

    namespace: str = Field(default="", alias="NAMESPACE")


class GiteaConfig(BackendConfig, NamespaceConfig):
    # Host-side script: the address comes from the Gitea provider's uri on the node, and an in-cluster host
    # (gitea.fn.svc) is reached through the Tilt port-forward on localhost.
    gitea_url: str

    @property
    def gitea_admin_user(self) -> str:
        return self.node.gitea_admin_user

    @property
    def gitea_host_uri(self) -> str:
        return to_host_url(self.gitea_url)

    @property
    def gitea_host_api_uri(self) -> str:
        return f"{self.gitea_host_uri}/api/v1"


class DagsterConfig(EnvConfig):
    dagster_url: str = Field(default="http://localhost:3000", alias="DAGSTER_URL")


class ProjectConfig(BackendConfig):
    project_name: str


class RepoConfig(GiteaConfig, ProjectConfig):
    """
    What both Gitea repos share. Each entity declares repo, repo_uri and token_name from its
    own env vars, and the token scope it needs.
    """

    # The address the sensor uses from inside the cluster: the provider's api_uri.
    gitea_api_uri: str
    # Set when the repo comes from a backend record: the label that record's secret has.
    backend_secret_label: str = Field(default="", validate_default=False)
    # Set when the repo comes from a backend record: the type of that record's provider.
    backend_provider_type: str = Field(default="", validate_default=False)
    # GitHub only: what init_git_secret stores in the repo's secret, for the backend to mint installation tokens from.
    github_app_id: str = Field(default="", alias="GH_APP_ID", validate_default=False)
    github_installation_id: str = Field(default="", alias="GH_INSTALLATION_ID", validate_default=False)
    github_private_key: str = Field(default="", alias="GH_PRIVATE_KEY", validate_default=False)
    # GitHub only: the researcher's own token for writing to the trigger repo. Without it, the one `gh auth login` stored.
    researcher_git_token: str = Field(default="", alias="RESEARCHER_GIT_TOKEN", validate_default=False)
    entity: ClassVar[str]
    token_scope: ClassVar[str]

    @property
    def git_provider(self) -> str:
        """The backend record's provider type, else, before there is a record, from the repo uri's host: github.com is GitHub, any other is Gitea."""
        if self.backend_provider_type:
            return self.backend_provider_type
        return "github" if normalise_repo_uri(self.repo_uri).split("/")[0] == "github.com" else "gitea"

    @property
    def is_github(self) -> bool:
        return self.git_provider == "github"

    @property
    def repo_path(self) -> str:
        """owner/repo: a Gitea repo is under the admin user, a GitHub one wherever its uri says."""
        if self.is_github:
            return "/".join(normalise_repo_uri(self.repo_uri).split("/")[-2:])
        return f"{self.gitea_admin_user}/{self.repo}"

    @property
    def web_url(self) -> str:
        """Where the repos' pages open from the host."""
        return "https://github.com" if self.is_github else self.gitea_url

    @property
    def pulls_page(self) -> str:
        return "pull" if self.is_github else "pulls"

    @property
    def provider_api_uri(self) -> str:
        """The provider's API as the sensor reaches it."""
        return GH_API_BASE_URL if self.is_github else self.gitea_api_uri

    @property
    def secret_label(self) -> str:
        return self.backend_secret_label or f"{self.repo}-creds"

    @property
    def provider_uri(self) -> str:
        """The backend's git provider for the repo's host: the scheme the sensor reaches it by, and the host."""
        return f"{urlparse(self.provider_api_uri).scheme}://{normalise_repo_uri(self.repo_uri).split('/')[0]}"


class TriggerRepoConfig(RepoConfig):
    repo: str
    repo_uri: str
    watch_dir: str
    # The branch the project watches, from the project's record. Stated, never guessed from the repo's default branch.
    base_branch: str = Field(default="", validate_default=False)
    # Gitea tells tokens apart by name: reusing one name for both entities would invalidate
    # the other entity's token.
    token_name: str = Field(default="fn-sensor", alias="GITEA_TOKEN_NAME")
    entity: ClassVar[str] = "trigger"
    token_scope: ClassVar[str] = "read:repository"


class ResultsRepoConfig(RepoConfig):
    repo: str
    repo_uri: str
    target_dir: str
    # The branch results pull requests start from and go into, from the project's record. Stated, never guessed.
    base_branch: str = Field(default="", validate_default=False)
    token_name: str = Field(default="fn-results", alias="GITEA_RESULTS_TOKEN_NAME")
    entity: ClassVar[str] = "results"
    token_scope: ClassVar[str] = "write:repository"


ENTITY_CONFIGS = {"trigger": TriggerRepoConfig, "results": ResultsRepoConfig}

entity_option = click.option(
    "--entity",
    type=click.Choice(list(ENTITY_CONFIGS)),
    default="trigger",
    show_default=True,
    help="Which Gitea repo to act on.",
)


def build_gitea_api(config: GiteaConfig) -> GiteaAdminAPI:
    password = get_k8s_secret(secret_name="gitea-admin", namespace=config.namespace, key="password")
    client = GiteaAdminClient(
        username=config.gitea_admin_user, password=password, base_uri=config.gitea_host_api_uri
    )
    web = GiteaWebClient(config.gitea_admin_user, password, base_uri=config.gitea_host_uri)
    return GiteaAdminAPI(client, config.gitea_admin_user, web)


def get_repository(config: RepoConfig, backend_api: FncliBackendAPI) -> TriggerRepository | ResultsRepository:
    """The repo's global record in the backend, which names its provider."""
    find = backend_api.find_trigger_repository if config.entity == "trigger" else backend_api.find_results_repository
    repository = find(config.repo_uri)
    if repository is None:
        raise click.ClickException(
            f"Backend {config.entity} repository {config.repo_uri} does not exist "
            f"(run fncli apply first)"
        )
    return repository


def build_researcher_git_api(config: RepoConfig) -> GiteaAdminAPI | GithubAPI:
    """
    What makes the trigger repo's branches, files and pull requests. That is the researcher's work, not the node's,
    so it uses no token the backend mints: Gitea as its admin user, GitHub with RESEARCHER_GIT_TOKEN or else the
    token of `gh auth login`.
    """
    if not config.is_github:
        return build_gitea_api(config)
    token = config.researcher_git_token
    if not token:
        try:
            token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise click.ClickException(
                "Writing to a GitHub repo needs RESEARCHER_GIT_TOKEN, or `gh auth login` for the gh CLI to give one"
            ) from error
    return GithubAPI(GithubClient(token))


def build_git_api(config: RepoConfig) -> GiteaAPI | GithubAPI:
    """
    What makes the repo's branches, files and pull requests, as Dagster builds it: the client for the provider the
    repo's backend record names, with a token the backend mints for the repository as a whole. The provider's api_uri is
    the in-cluster address, so it goes through the port-forward.
    """
    backend_api = build_backend_api(config)
    repository = get_repository(config, backend_api)
    provider = repository.provider.model_copy(update={"api_uri": to_host_url(repository.provider.api_uri)})
    return GitAPIFactory(backend_api).for_repository(repository.model_copy(update={"provider": provider}))


def build_backend_api(config: BackendConfig) -> FncliBackendAPI:
    """Logs in as the dagster system user, the identity the sensors use."""
    adapter = BackendAdapter(
        base_url=config.node.url,
        username=get_k8s_secret(
            secret_name="dagster-keycloak-creds",
            namespace=config.node.keycloak_namespace,
            key="DAGSTER_KC_USER",
        ),
        password=get_k8s_secret(
            secret_name="dagster-keycloak-creds",
            namespace=config.node.keycloak_namespace,
            key="DAGSTER_KC_PASSWORD",
        ),
    )
    return FncliBackendAPI(BackendSession(adapter))


def build_admin_backend_api(config: BackendConfig) -> FncliBackendAPI:
    """Logs in as the first Keycloak user (an Administrator), which deploy.sh stores in the keycloak-first-user secret."""
    adapter = BackendAdapter(
        base_url=config.node.url,
        username=get_k8s_secret(secret_name="keycloak-first-user", namespace=config.node.keycloak_namespace, key="EMAIL"),
        password=get_k8s_secret(secret_name="keycloak-first-user", namespace=config.node.keycloak_namespace, key="PASSWORD"),
    )
    return FncliBackendAPI(BackendSession(adapter))
