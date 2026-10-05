"""
Commands for the secrets that hold credentials: a Gitea token for each repo and dummy
database credentials for the dataset.
"""

import logging

import click

from fncli.cmds.common import (
    ROLE_CONFIGS,
    SECRET_CONFIGS,
    DatasetConfig,
    RepoConfig,
    build_backend_api,
    build_gitea_api,
    find_project,
    init_backend_project,
    role_option,
)
from fncli.cmds.repository import init_gitea_repo
from fncli.dagster.backend import BackendAPI
from fncli.dagster.gitea import GiteaAdminAPI, GiteaAPI, GiteaClient
from fncli.dagster.k8s import get_k8s_secret
from fncli.dagster.models import Project

logger = logging.getLogger("secret")

# The dataset is a stand-in: nothing connects to it, so its credentials are dummies.
DATASET_DUMMY_CREDENTIALS = {"USERNAME": "dummy", "PASSWORD": "dummy"}


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


@click.command("delete-secret")
@click.option(
    "--role",
    type=click.Choice(list(SECRET_CONFIGS)),
    default="trigger",
    show_default=True,
    help="Whose secret: a repo's, or the dataset's.",
)
def delete_secret_command(role):
    """Delete a secret from the backend and the K8s secret behind it. Nothing may use it."""
    config = SECRET_CONFIGS[role]()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    if project is None:
        return
    if backend_api.delete_secret(project.id, config.secret_label):
        logger.info(f"Deleted secret {config.secret_label} of project {project.id}")
    else:
        logger.info(f"Secret {config.secret_label} of project {project.id} does not exist")


@click.command("delete-gitea-token")
@role_option
def delete_gitea_token_command(role):
    """Delete the Gitea token that init-git-secret created for a repo."""
    config = ROLE_CONFIGS[role]()
    if build_gitea_api(config).delete_token(config.token_name):
        logger.info(f"Deleted Gitea token {config.token_name!r}")
    else:
        logger.info(f"Gitea token {config.token_name!r} does not exist")


COMMANDS = [
    init_git_secret_command,
    init_dataset_secret_command,
    verify_git_secret_command,
    delete_secret_command,
    delete_gitea_token_command,
]
