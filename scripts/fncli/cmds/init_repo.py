"""
Commands that set up what the trigger simulation builds on: two Gitea repos (the trigger
repo the sensor watches and the results repo tasks write to), the webserver Project, a
secret for each repo and for the dataset, and the backend records that tie them together.
Each step is its own idempotent command; `setup-project` runs them in order.
"""

import json
import logging
from typing import ClassVar

import click
from pydantic import Field

from fncli.dagster.backend import BackendAPI
from fncli.dagster.config import EnvConfig
from fncli.dagster.gitea import GiteaAdminAPI, GiteaAdminClient, GiteaAPI, GiteaClient
from fncli.dagster.k8s import get_k8s_secret
from fncli.dagster.models import Dataset, Project, ResultsRepository, TriggerRepository
from fncli.dagster.utils import BackendAdapter, BackendSession

logger = logging.getLogger("init_repo")

# The dataset is a stand-in: nothing connects to it, so its details are dummies.
DATASET_HOST = "db-datasets.fn.svc"
DATASET_PORT = 5432
DATASET_TYPE = "postgres"
DATASET_READ_SCHEMA = "cdm"
DATASET_WRITE_SCHEMA = "results"
DATASET_DUMMY_CREDENTIALS = {"USERNAME": "dummy", "PASSWORD": "dummy"}


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
    What both Gitea repos share. Each role declares repo, repo_uri and token_name from its
    own env vars, and the token scope it needs.
    """

    # The address the sensor uses from inside the cluster.
    gitea_api_uri: str = Field(default="", alias="GITEA_API_URI")
    token_scope: ClassVar[str]

    @property
    def secret_label(self) -> str:
        return f"{self.repo}-creds"


class TriggerRepoConfig(RepoConfig):
    repo: str = Field(default="", alias="TEST_TRIGGER_REPO")
    repo_uri: str = Field(default="", alias="TEST_TRIGGER_REPO_URI")
    watch_dir: str = Field(default="", alias="TEST_TRIGGER_REPO_WATCH_DIR")
    # Gitea tells tokens apart by name: reusing one name for both roles would invalidate
    # the other role's token.
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


ROLE_CONFIGS = {"trigger": TriggerRepoConfig, "results": ResultsRepoConfig}
SECRET_CONFIGS = {**ROLE_CONFIGS, "dataset": DatasetConfig}

role_option = click.option(
    "--role",
    type=click.Choice(list(ROLE_CONFIGS)),
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


def init_gitea_repo(config: RepoConfig, gitea_api: GiteaAdminAPI) -> dict:
    gitea_repo = gitea_api.get_or_create_repo(config.repo, "Trigger-repository simulation")
    logger.info(f"Gitea repo: {gitea_repo['html_url']} (default branch {gitea_repo['default_branch']})")
    return gitea_repo


def init_backend_project(config: ProjectConfig, backend_api: BackendAPI) -> Project:
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


def find_project(config: ProjectConfig, backend_api: BackendAPI) -> Project | None:
    """For the delete steps: a project that is already gone is not an error."""
    project = backend_api.find_project(config.project_name)
    if project is None:
        logger.info(f"Backend project {config.project_name} does not exist")
    return project


def init_git_secret(
    config: RepoConfig, gitea_api: GiteaAdminAPI, backend_api: BackendAPI, project: Project
) -> str:
    """Store a fresh Gitea token where the backend reads it."""
    token = gitea_api.replace_token(config.token_name, [config.token_scope])
    secret = backend_api.upsert_secret(project.id, config.secret_label, {"TOKEN": token})
    stored = get_k8s_secret(
        secret_name=secret["key"], namespace=secret["namespace"], key="TOKEN"
    )
    if stored != token:
        raise RuntimeError(
            f"Secret {secret['key']} in {secret['namespace']} does not hold the new token"
        )
    logger.info(
        f"Secret {config.secret_label} of project {project.id} is {secret['key']} "
        f"in namespace {secret['namespace']} and holds the new token "
        f"(Gitea token {config.token_name!r}, scope {config.token_scope})"
    )
    return token


def verify_gitea_accepts_bearer_token(config: RepoConfig, token: str, gitea_repo: dict):
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


def init_dataset_secret(config: DatasetConfig, backend_api: BackendAPI, project: Project) -> dict:
    """The dataset is a stand-in, so its credentials are dummies."""
    secret = backend_api.upsert_secret(
        project.id, config.secret_label, DATASET_DUMMY_CREDENTIALS
    )
    logger.info(f"Secret {config.secret_label} of project {project.id} is {secret['key']}")
    return secret


def init_backend_trigger_repo(
    config: TriggerRepoConfig, backend_api: BackendAPI, project: Project, gitea_repo: dict
) -> TriggerRepository:
    repo = backend_api.get_or_create_repository(
        uri=config.repo_uri,
        provider="gitea",
        api_uri=config.gitea_api_uri,
        secret_label=config.secret_label,
        watch_dir=config.watch_dir,
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


def init_backend_results_repo(
    config: ResultsRepoConfig, backend_api: BackendAPI, project: Project
) -> ResultsRepository:
    repo = backend_api.get_or_create_results_repository(
        project.id,
        uri=config.repo_uri,
        provider="gitea",
        api_uri=config.gitea_api_uri,
        secret_label=config.secret_label,
        target_dir=config.target_dir,
    )
    logger.info(
        f"Backend results repository {repo.id}: {repo.uri} "
        f"(provider {repo.provider}, api_uri {repo.api_uri}, secret {repo.secret.label}, "
        f"target_dir {repo.target_dir}, project {repo.project_id})"
    )
    return repo


def init_backend_dataset(
    config: DatasetConfig, backend_api: BackendAPI, project: Project
) -> Dataset:
    dataset = backend_api.get_or_create_dataset(
        config.dataset_name,
        project.id,
        host=DATASET_HOST,
        port=DATASET_PORT,
        db_type=DATASET_TYPE,
        secret_label=config.secret_label,
        read_schema=DATASET_READ_SCHEMA,
        write_schema=DATASET_WRITE_SCHEMA,
    )
    logger.info(
        f"Backend dataset {dataset.id}: {dataset.name} ({dataset.type} at "
        f"{dataset.host}:{dataset.port}, secret {dataset.secret.label}, "
        f"project {dataset.project_id})"
    )
    return dataset


@click.command("init-gitea-repo")
@role_option
def init_gitea_repo_command(role):
    """Find or create a repo in Gitea."""
    config = ROLE_CONFIGS[role]()
    init_gitea_repo(config, build_gitea_api(config))


@click.command("init-backend-project")
def init_backend_project_command():
    """Find or create the test project in the backend, and enable it."""
    config = ProjectConfig()
    init_backend_project(config, build_backend_api(config))


@click.command("init-git-secret")
@role_option
def init_git_secret_command(role):
    """Store a fresh Gitea token in the K8s secret of a repo (read for trigger, write for results)."""
    config = ROLE_CONFIGS[role]()
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    init_git_secret(
        config=config,
        gitea_api=build_gitea_api(config),
        backend_api=backend_api,
        project=project,
    )


@click.command("init-dataset-secret")
def init_dataset_secret_command():
    """Store dummy database credentials in the K8s secret of the dataset."""
    config = DatasetConfig()
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    init_dataset_secret(config, backend_api, project)


@click.command("verify-git-secret")
@role_option
def verify_git_secret_command(role):
    """Check Gitea accepts the token currently stored in a repo's secret."""
    config = ROLE_CONFIGS[role]()
    gitea_repo = init_gitea_repo(config, build_gitea_api(config))
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    secret = backend_api.get_secret(project.id, config.secret_label)
    token = get_k8s_secret(
        secret_name=secret["key"], namespace=secret["namespace"], key="TOKEN"
    )
    verify_gitea_accepts_bearer_token(config=config, token=token, gitea_repo=gitea_repo)


@click.command("init-backend-trigger-repo")
def init_backend_trigger_repo_command():
    """Register the trigger repo with the backend so the sensor polls it."""
    config = TriggerRepoConfig()
    backend_api = build_backend_api(config)
    gitea_repo = init_gitea_repo(config, build_gitea_api(config))
    project = init_backend_project(config, backend_api)
    init_backend_trigger_repo(
        config=config,
        backend_api=backend_api,
        project=project,
        gitea_repo=gitea_repo,
    )


@click.command("init-backend-results-repo")
def init_backend_results_repo_command():
    """Register the results repo with the backend as the project's results repository."""
    config = ResultsRepoConfig()
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    init_backend_results_repo(config, backend_api, project)


@click.command("init-backend-dataset")
def init_backend_dataset_command():
    """Register the dummy dataset with the backend (needs its secret, see init-dataset-secret)."""
    config = DatasetConfig()
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    init_backend_dataset(config, backend_api, project)


def get_project_healthcheck(config: ProjectConfig, backend_api: BackendAPI) -> dict:
    project = backend_api.find_project(config.project_name)
    if project is None:
        raise click.ClickException(
            f"Project {config.project_name} not found, run init-backend-project first"
        )
    return backend_api.get_project_healthcheck(project.id)


@click.command("project-healthcheck")
def project_healthcheck_command():
    """Print the backend's healthcheck for the test project, as JSON. Exits 1 unless it is ok."""
    config = ProjectConfig()
    health = get_project_healthcheck(config, build_backend_api(config))
    click.echo(json.dumps(health, indent=2))
    if health["status"] != "ok":
        raise click.exceptions.Exit(1)


# Each step with the options it runs with.
STEPS = [
    (init_backend_project_command, {}),
    (init_gitea_repo_command, {"role": "trigger"}),
    (init_gitea_repo_command, {"role": "results"}),
    (init_git_secret_command, {"role": "trigger"}),
    (init_git_secret_command, {"role": "results"}),
    (init_dataset_secret_command, {}),
    (init_backend_trigger_repo_command, {}),
    (init_backend_results_repo_command, {}),
    (init_backend_dataset_command, {}),
    (verify_git_secret_command, {"role": "trigger"}),
    (verify_git_secret_command, {"role": "results"}),
    (project_healthcheck_command, {}),
]


@click.command("setup-project")
@click.pass_context
def setup_project_command(ctx):
    """Set up a whole dev project: two Gitea repos, secrets, and the backend records."""
    for step, options in STEPS:
        logger.info(f"=== {step.name} {options or ''} ===")
        ctx.invoke(step, **options)


@click.command("delete-gitea-repo")
@role_option
@click.confirmation_option("-y", "--yes", prompt="Delete the Gitea repo and all its pull requests?")
def delete_gitea_repo_command(role):
    """Delete a repo from Gitea. The backend's records of it are left alone."""
    config = ROLE_CONFIGS[role]()
    if build_gitea_api(config).delete_repo(config.repo):
        logger.info(f"Deleted Gitea repo {config.gitea_admin_user}/{config.repo}")
    else:
        logger.info(f"Gitea repo {config.gitea_admin_user}/{config.repo} does not exist")


COMMANDS = [
    init_gitea_repo_command,
    init_backend_project_command,
    init_git_secret_command,
    init_dataset_secret_command,
    verify_git_secret_command,
    init_backend_trigger_repo_command,
    init_backend_results_repo_command,
    init_backend_dataset_command,
    setup_project_command,
    project_healthcheck_command,
    delete_gitea_repo_command,
]
