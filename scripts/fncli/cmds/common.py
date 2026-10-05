"""
Config and helpers shared by the commands: what the env holds, and the Gitea and backend
APIs built from it.
"""

from typing import ClassVar

import click
from pydantic import Field

from fncli.dagster.backend import BackendAPI
from fncli.dagster.config import EnvConfig
from fncli.dagster.gitea import GiteaAdminAPI, GiteaAdminClient
from fncli.dagster.k8s import get_k8s_secret
from fncli.dagster.utils import BackendAdapter, BackendSession

class GiteaConfig(EnvConfig):
    # Host-side script, so it needs the port-forwarded addresses, not in-cluster DNS.
    gitea_url: str = Field(default="http://localhost:4000", alias="GITEA_URL")
    gitea_admin_user: str = Field(default="gitea_admin", alias="GITEA_ADMIN_USER")
    namespace: str = Field(default="", alias="NAMESPACE")

    @property
    def gitea_host_api_uri(self) -> str:
        return f"{self.gitea_url}/api/v1"


class BackendConfig(EnvConfig):
    keycloak_namespace: str = Field(default="", alias="KEYCLOAK_NAMESPACE")
    backend_url: str = Field(default="", alias="BACKEND_URL")


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
    backend_secret_label: str = ""
    token_scope: ClassVar[str]

    @property
    def secret_label(self) -> str:
        return self.backend_secret_label or f"{self.repo}-creds"


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

    @property
    def secret_label(self) -> str:
        return f"{self.project_name}-dataset-creds"


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


def build_backend_api(config: BackendConfig) -> BackendAPI:
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
    return BackendAPI(BackendSession(adapter))
