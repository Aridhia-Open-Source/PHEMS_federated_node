"""
Commands that set up what the trigger simulation builds on: the Gitea repo, the webserver
Project, the git token secret the sensor reads, and the TriggerRepository that ties them
together. Each step is its own idempotent command; `init-repo` runs them in order.
"""

import json
import logging

import click
from pydantic import Field

from fncli.dagster.backend import BackendAPI
from fncli.dagster.config import EnvConfig
from fncli.dagster.gitea import GiteaAdminAPI, GiteaAdminClient, GiteaAPI, GiteaClient
from fncli.dagster.k8s import get_k8s_secret
from fncli.dagster.models import Project, TriggerRepository
from fncli.dagster.utils import BackendAdapter, BackendSession

logger = logging.getLogger("init_repo")


class InitRepoConfig(EnvConfig):
    # Host-side script, so it needs the port-forwarded addresses, not in-cluster DNS.
    gitea_url: str = Field(default="http://localhost:4000", alias="GITEA_URL")
    gitea_admin_user: str = Field(default="gitea_admin", alias="GITEA_ADMIN_USER")
    # The address the sensor uses from inside the cluster.
    gitea_api_uri: str = Field(default="", alias="GITEA_API_URI")
    gitea_token_name: str = Field(default="fn-sensor", alias="GITEA_TOKEN_NAME")
    namespace: str = Field(default="", alias="NAMESPACE")
    keycloak_namespace: str = Field(default="", alias="KEYCLOAK_NAMESPACE")
    backend_url: str = Field(default="", alias="BACKEND_URL")
    trigger_repo: str = Field(default="", alias="TEST_TRIGGER_REPO")
    trigger_repo_uri: str = Field(default="", alias="TEST_TRIGGER_REPO_URI")
    trigger_repo_watch_dir: str = Field(default="", alias="TEST_TRIGGER_REPO_WATCH_DIR")
    project_name: str = Field(default="", alias="TEST_PROJECT_NAME")

    @property
    def gitea_host_api_uri(self) -> str:
        return f"{self.gitea_url}/api/v1"

    @property
    def git_secret_label(self) -> str:
        return f"{self.trigger_repo}-creds"


def build_gitea_api(config: InitRepoConfig) -> GiteaAdminAPI:
    client = GiteaAdminClient(
        username=config.gitea_admin_user,
        password=get_k8s_secret(
            secret_name="gitea-admin", namespace=config.namespace, key="password"
        ),
        base_uri=config.gitea_host_api_uri,
    )
    return GiteaAdminAPI(client, config.gitea_admin_user)


def build_backend_api(config: InitRepoConfig) -> BackendAPI:
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


def init_gitea_repo(config: InitRepoConfig, gitea_api: GiteaAdminAPI) -> dict:
    gitea_repo = gitea_api.get_or_create_repo(config.trigger_repo, "Trigger-repository simulation")
    logger.info(f"Gitea repo: {gitea_repo['html_url']} (default branch {gitea_repo['default_branch']})")
    return gitea_repo


def init_backend_project(config: InitRepoConfig, backend_api: BackendAPI) -> Project:
    """The simulation needs sensors to act on this project, so make sure it is enabled."""
    project = backend_api.get_or_create_project(
        name=config.project_name,
        description="Trigger-repository simulation",
        enabled=True,
    )
    if not project.enabled:
        project = backend_api.patch_project(project.id, {"enabled": True})
    logger.info(f"Backend project: {project.name} (id {project.id}, enabled {project.enabled})")
    return project


def init_git_secret(
    config: InitRepoConfig, gitea_api: GiteaAdminAPI, backend_api: BackendAPI, project: Project
) -> str:
    """Store a fresh Gitea token where the sensor reads it."""
    token = gitea_api.replace_token(config.gitea_token_name, ["read:repository"])
    secret = backend_api.upsert_secret(project.id, config.git_secret_label, {"TOKEN": token})
    stored = get_k8s_secret(
        secret_name=secret["key"], namespace=config.namespace, key="TOKEN"
    )
    if stored != token:
        raise RuntimeError(
            f"Secret {secret['key']} in {config.namespace} does not hold the new token"
        )
    logger.info(
        f"Secret {config.git_secret_label} of project {project.id} is {secret['key']} "
        f"in namespace {config.namespace} and holds the new token "
        f"(Gitea token {config.gitea_token_name!r})"
    )
    return token


def verify_gitea_accepts_bearer_token(config: InitRepoConfig, token: str, gitea_repo: dict):
    """Raises if Gitea rejects the token, as the sensor would when it polls."""
    # base_uri is keyword-only in practice: the second positional parameter is a session.
    sensor_api = GiteaAPI(GiteaClient(token, base_uri=config.gitea_host_api_uri))
    merged_pulls = sensor_api.get_new_merged_pulls(
        repo_path=gitea_repo["full_name"],
        base_branch=gitea_repo["default_branch"],
        merged_after="",
    )
    logger.info(
        f"Gitea accepted the token as a bearer token: "
        f"{len(merged_pulls)} merged PR(s) on {gitea_repo['default_branch']}"
    )


def init_backend_trigger_repo(
    config: InitRepoConfig, backend_api: BackendAPI, project: Project, gitea_repo: dict
) -> TriggerRepository:
    repo = backend_api.get_or_create_repository(
        uri=config.trigger_repo_uri,
        provider="gitea",
        api_uri=config.gitea_api_uri,
        secret_name=config.git_secret_label,
        watch_dir=config.trigger_repo_watch_dir,
        base_branch=gitea_repo["default_branch"],
        project_id=project.id,
    )
    logger.info(
        f"Backend trigger repository {repo.id}: {repo.uri} "
        f"(provider {repo.provider}, api_uri {repo.api_uri}, secret {repo.secret.label}, "
        f"branch {repo.base_branch}, watch_dir {repo.watch_dir}, project {repo.project_id}, "
        f"pr_cursor {repo.pr_cursor})"
    )
    return repo


@click.command("init-gitea-repo")
def init_gitea_repo_command():
    """Find or create the test repo in Gitea."""
    config = InitRepoConfig()
    init_gitea_repo(config, build_gitea_api(config))


@click.command("init-backend-project")
def init_backend_project_command():
    """Find or create the test project in the backend, and enable it."""
    config = InitRepoConfig()
    init_backend_project(config, build_backend_api(config))


@click.command("init-git-secret")
def init_git_secret_command():
    """Store a fresh Gitea token in the K8s secret the sensor reads."""
    config = InitRepoConfig()
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    init_git_secret(
        config=config,
        gitea_api=build_gitea_api(config),
        backend_api=backend_api,
        project=project,
    )


@click.command("verify-git-secret")
def verify_git_secret_command():
    """Check Gitea accepts the token currently stored in the sensor's secret."""
    config = InitRepoConfig()
    gitea_repo = init_gitea_repo(config, build_gitea_api(config))
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    secret = backend_api.get_secret(project.id, config.git_secret_label)
    token = get_k8s_secret(
        secret_name=secret["key"], namespace=config.namespace, key="TOKEN"
    )
    verify_gitea_accepts_bearer_token(config=config, token=token, gitea_repo=gitea_repo)


@click.command("init-backend-trigger-repo")
def init_backend_trigger_repo_command():
    """Register the test repo with the backend so the sensor polls it."""
    config = InitRepoConfig()
    backend_api = build_backend_api(config)
    gitea_repo = init_gitea_repo(config, build_gitea_api(config))
    project = init_backend_project(config, backend_api)
    init_backend_trigger_repo(
        config=config,
        backend_api=backend_api,
        project=project,
        gitea_repo=gitea_repo,
    )


STEPS = [
    init_gitea_repo_command,
    init_backend_project_command,
    init_git_secret_command,
    verify_git_secret_command,
    init_backend_trigger_repo_command,
]


@click.command("init-repo")
@click.pass_context
def init_repo_command(ctx):
    """Run every init step, in order."""
    for step in STEPS:
        logger.info(f"=== {step.name} ===")
        ctx.invoke(step)


def get_project_healthcheck(config: InitRepoConfig, backend_api: BackendAPI) -> dict:
    project = next(
        (p for p in backend_api.get_projects() if p.name == config.project_name), None
    )
    if project is None:
        raise click.ClickException(
            f"Project {config.project_name} not found, run init-backend-project first"
        )
    return backend_api.get_project_healthcheck(project.id)


@click.command("project-healthcheck")
def project_healthcheck_command():
    """Print the backend's healthcheck for the test project, as JSON. Exits 1 unless it is ok."""
    config = InitRepoConfig()
    health = get_project_healthcheck(config, build_backend_api(config))
    click.echo(json.dumps(health, indent=2))
    if health["status"] != "ok":
        raise click.exceptions.Exit(1)


@click.command("delete-gitea-repo")
@click.confirmation_option("-y", "--yes", prompt="Delete the Gitea repo and all its pull requests?")
def delete_gitea_repo_command():
    """Delete the test repo from Gitea. The backend's records of it are left alone."""
    config = InitRepoConfig()
    if build_gitea_api(config).delete_repo(config.trigger_repo):
        logger.info(f"Deleted Gitea repo {config.gitea_admin_user}/{config.trigger_repo}")
    else:
        logger.info(f"Gitea repo {config.gitea_admin_user}/{config.trigger_repo} does not exist")


COMMANDS = [*STEPS, init_repo_command, project_healthcheck_command, delete_gitea_repo_command]
