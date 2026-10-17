"""
Commands for the secrets that hold credentials: a Gitea token for each repo and dummy
database credentials for the dataset (dummies unless DATASET_USERNAME and DATASET_PASSWORD are set).
Secrets are global, they belong to no project.
"""

import logging

import click

from fncli.cmds.common import (
    SECRET_CONFIGS,
    DatasetConfig,
    RepoConfig,
    build_backend_api,
    build_gitea_api,
    entity_option,
)
from fncli.cmds.repository import backend_source_options, init_gitea_repo, load_repo_config
from fncli.backend import FncliBackendAPI
from app.gitea import GiteaAPI, GiteaClient
from fncli.gitea import GiteaAdminAPI
from fncli.k8s import get_k8s_secret

logger = logging.getLogger("secret")

# What a git secret holds until init-git-secret writes a real token into it.
GIT_PLACEHOLDER = {"TOKEN": "unset"}


def init_git_secret(config: RepoConfig, gitea_api: GiteaAdminAPI, backend_api: FncliBackendAPI) -> str:
    """Store a fresh Gitea token where the backend reads it."""
    token = gitea_api.replace_token(config.token_name, [config.token_scope])
    secret = backend_api.upsert_secret(config.secret_label, {"TOKEN": token})
    stored = get_k8s_secret(
        secret_name=secret["key"], namespace=secret["namespace"], key="TOKEN"
    )
    if stored != token:
        raise RuntimeError(
            f"Secret {secret['key']} in {secret['namespace']} does not hold the new token"
        )
    logger.info(
        f"Secret {config.secret_label} is {secret['key']} "
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
        merged_after="",
    )
    logger.info(
        f"Gitea accepted the token as a bearer token: "
        f"{len(merged_pulls)} merged PR(s) on {gitea_repo['default_branch']}"
    )


def dataset_credentials(config: DatasetConfig) -> dict:
    return {"USERNAME": config.dataset_username, "PASSWORD": config.dataset_password}


def init_dataset_secret(config: DatasetConfig, backend_api: FncliBackendAPI) -> dict:
    secret = backend_api.upsert_secret(config.secret_label, dataset_credentials(config))
    logger.info(f"Secret {config.secret_label} is {secret['key']}")
    return secret


@click.command("init-git-secret")
@entity_option
@backend_source_options
def init_git_secret_command(entity, from_backend, project):
    """Store a fresh Gitea token in the K8s secret of a repo (read for trigger, write for results)."""
    config = load_repo_config(entity, from_backend, project)
    init_git_secret(
        config=config,
        gitea_api=build_gitea_api(config),
        backend_api=build_backend_api(config),
    )


@click.command("init-dataset-secret")
def init_dataset_secret_command():
    """Store the database credentials in the K8s secret of the dataset."""
    config = DatasetConfig()
    init_dataset_secret(config, build_backend_api(config))


def init_backend_secret(config: RepoConfig | DatasetConfig, backend_api: FncliBackendAPI):
    """Create the secret with placeholder values unless it exists, so a real token is kept."""
    label = config.secret_label
    if any(secret["label"] == label for secret in backend_api.get_secrets()):
        logger.info(f"Secret {label} already exists")
        return
    values = dataset_credentials(config) if isinstance(config, DatasetConfig) else GIT_PLACEHOLDER
    secret = backend_api.upsert_secret(label, values)
    logger.info(f"Secret {label} is {secret['key']}, with placeholder values")


@click.command("init-backend-secret")
@click.option(
    "--entity",
    type=click.Choice(list(SECRET_CONFIGS)),
    default="trigger",
    show_default=True,
    help="Whose secret: a repo's, or the dataset's.",
)
def init_backend_secret_command(entity):
    """Create a secret in the backend with placeholder values, with no Gitea call (see init-git-secret)."""
    config = SECRET_CONFIGS[entity]()
    init_backend_secret(config, build_backend_api(config))


@click.command("verify-git-secret")
@entity_option
@backend_source_options
def verify_git_secret_command(entity, from_backend, project):
    """Check Gitea accepts the token currently stored in a repo's secret."""
    config = load_repo_config(entity, from_backend, project)
    gitea_repo = init_gitea_repo(config, build_gitea_api(config))
    secret = build_backend_api(config).get_secret(config.secret_label)
    token = get_k8s_secret(
        secret_name=secret["key"], namespace=secret["namespace"], key="TOKEN"
    )
    verify_gitea_accepts_bearer_token(config=config, token=token, gitea_repo=gitea_repo)


@click.command("delete-secret")
@click.option(
    "--entity",
    type=click.Choice(list(SECRET_CONFIGS)),
    default="trigger",
    show_default=True,
    help="Whose secret: a repo's, or the dataset's.",
)
def delete_secret_command(entity):
    """Delete a secret from the backend and the K8s secret behind it. Nothing may use it."""
    config = SECRET_CONFIGS[entity]()
    backend_api = build_backend_api(config)
    if backend_api.delete_secret(config.secret_label):
        logger.info(f"Deleted secret {config.secret_label}")
    else:
        logger.info(f"Secret {config.secret_label} does not exist")


@click.command("delete-gitea-token")
@entity_option
@backend_source_options
def delete_gitea_token_command(entity, from_backend, project):
    """Delete the Gitea token that init-git-secret created for a repo."""
    config = load_repo_config(entity, from_backend, project)
    if build_gitea_api(config).delete_token(config.token_name):
        logger.info(f"Deleted Gitea token {config.token_name!r}")
    else:
        logger.info(f"Gitea token {config.token_name!r} does not exist")


COMMANDS = [
    init_git_secret_command,
    init_dataset_secret_command,
    init_backend_secret_command,
    verify_git_secret_command,
    delete_secret_command,
    delete_gitea_token_command,
]
