"""
Config and helpers shared by the commands: what the env holds, and the Gitea and backend
APIs built from it.
"""

from typing import ClassVar
from urllib.parse import urlparse

import click
from pydantic import Field

from fncli.backend import FncliBackendAPI
from app.config import EnvConfig
from app.git_uri import normalise_repo_uri
from fncli.gitea import GiteaAdminAPI, GiteaAdminClient
from fncli.k8s import get_k8s_secret
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


class GiteaConfig(EnvConfig):
    # Host-side script, so it needs the port-forwarded addresses, not in-cluster DNS.
    gitea_url: str = Field(default="http://localhost:4000", alias="GITEA_URL")
    gitea_admin_user: str = Field(default="gitea_admin", alias="GITEA_ADMIN_USER")
    namespace: str = Field(default="", alias="NAMESPACE")

    @property
    def gitea_host_api_uri(self) -> str:
        return to_host_url(f"{self.gitea_url}/api/v1")


class DagsterConfig(EnvConfig):
    dagster_url: str = Field(default="http://localhost:3000", alias="DAGSTER_URL")


class BackendConfig(EnvConfig):
    keycloak_namespace: str = Field(default="", alias="KEYCLOAK_NAMESPACE")
    backend_url: str = Field(default="", alias="BACKEND_URL")


class AdminConfig(EnvConfig):
    """Optional: an admin user of the backend. Revoking a link is admin only and the dagster system user is refused (403)."""

    admin_user: str = Field(default="", alias="FNCLI_ADMIN_USER", validate_default=False)
    admin_password: str = Field(default="", alias="FNCLI_ADMIN_PASSWORD", validate_default=False)


class ProjectConfig(BackendConfig):
    project_name: str = Field(default="", alias="TEST_PROJECT_NAME")


class RepoConfig(GiteaConfig, ProjectConfig):
    """
    What both Gitea repos share. Each entity declares repo, repo_uri and token_name from its
    own env vars, and the token scope it needs.
    """

    # The address the sensor uses from inside the cluster.
    gitea_api_uri: str = Field(default="", alias="GITEA_API_URI")
    # Set when the repo comes from a backend record: the label that record's secret has.
    backend_secret_label: str = Field(default="", validate_default=False)
    token_scope: ClassVar[str]

    @property
    def secret_label(self) -> str:
        return self.backend_secret_label or f"{self.repo}-creds"

    @property
    def provider_uri(self) -> str:
        """The backend's git provider for the repo's host: the scheme the sensor reaches it by, and the host."""
        return f"{urlparse(self.gitea_api_uri).scheme}://{normalise_repo_uri(self.repo_uri).split('/')[0]}"


class TriggerRepoConfig(RepoConfig):
    repo: str = Field(default="", alias="TEST_TRIGGER_REPO")
    repo_uri: str = Field(default="", alias="TEST_TRIGGER_REPO_URI")
    watch_dir: str = Field(default="", alias="TEST_TRIGGER_REPO_WATCH_DIR")
    # Gitea tells tokens apart by name: reusing one name for both entities would invalidate
    # the other entity's token.
    token_name: str = Field(default="fn-sensor", alias="GITEA_TOKEN_NAME")
    token_scope: ClassVar[str] = "read:repository"


class ResultsRepoConfig(RepoConfig):
    repo: str = Field(default="", alias="TEST_RESULTS_REPO")
    repo_uri: str = Field(default="", alias="TEST_RESULTS_REPO_URI")
    target_dir: str = Field(default="", alias="TEST_RESULTS_TARGET_DIR")
    token_name: str = Field(default="fn-results", alias="GITEA_RESULTS_TOKEN_NAME")
    token_scope: ClassVar[str] = "write:repository"


class DatasetConfig(ProjectConfig):
    dataset_name: str = Field(default="", alias="DEFAULT_PROJECT_DATASET")
    # The defaults are the dummy stand-in dataset. `make uc1-seed` sets these from dev.db/.env.
    dataset_host: str = Field(default="db-datasets.fn.svc", alias="CLUSTER_DATASET_HOST")
    dataset_port: int = Field(default=5432, alias="DATASET_PORT")
    dataset_type: str = Field(default="postgres", alias="DATASET_TYPE")
    dataset_read_schema: str = Field(default="cdm", alias="DATASET_SCHEMA")
    dataset_write_schema: str = Field(default="results", alias="DATASET_SCHEMA_WRITE")
    dataset_username: str = Field(default="dummy", alias="DATASET_USERNAME")
    dataset_password: str = Field(default="dummy", alias="DATASET_PASSWORD")

    @property
    def secret_label(self) -> str:
        return f"{self.dataset_name}-dataset-creds"


ENTITY_CONFIGS = {"trigger": TriggerRepoConfig, "results": ResultsRepoConfig}
SECRET_CONFIGS = {**ENTITY_CONFIGS, "dataset": DatasetConfig}

entity_option = click.option(
    "--entity",
    type=click.Choice(list(ENTITY_CONFIGS)),
    default="trigger",
    show_default=True,
    help="Which Gitea repo to act on.",
)


def build_gitea_api(config: GiteaConfig) -> GiteaAdminAPI:
    client = GiteaAdminClient(
        username=config.gitea_admin_user,
        password=get_k8s_secret(
            secret_name="gitea-admin", namespace=config.namespace, key="password"
        ),
        base_uri=config.gitea_host_api_uri,
    )
    return GiteaAdminAPI(client, config.gitea_admin_user)


def build_backend_api(config: BackendConfig) -> FncliBackendAPI:
    """Logs in as the dagster system user, the identity the sensors use."""
    adapter = BackendAdapter(
        base_url=config.backend_url,
        username=get_k8s_secret(
            secret_name="dagster-keycloak-creds",
            namespace=config.keycloak_namespace,
            key="DAGSTER_KC_USER",
        ),
        password=get_k8s_secret(
            secret_name="dagster-keycloak-creds",
            namespace=config.keycloak_namespace,
            key="DAGSTER_KC_PASSWORD",
        ),
    )
    return FncliBackendAPI(BackendSession(adapter))


def build_admin_backend_api(config: BackendConfig) -> FncliBackendAPI | None:
    """Logs in as the admin user named by FNCLI_ADMIN_USER and FNCLI_ADMIN_PASSWORD, or None when they are not set."""
    admin = AdminConfig()
    if not (admin.admin_user and admin.admin_password):
        return None
    adapter = BackendAdapter(base_url=config.backend_url, username=admin.admin_user, password=admin.admin_password)
    return FncliBackendAPI(BackendSession(adapter))
