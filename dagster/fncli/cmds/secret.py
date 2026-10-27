"""
Commands for the secrets that hold credentials: what the backend mints git tokens from for each
repo (ADR 0023: Gitea OAuth2 credentials, a GitHub App, or a static token) and dummy
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
    build_git_api,
    entity_option,
)
from fncli.cmds.repository import backend_source_options, init_gitea_repo, load_repo_config
from fncli.backend import FncliBackendAPI
from app.gitea import GiteaAPI, GiteaClient
from app.github import GithubAPI, GithubClient
from fncli.gitea import GiteaAdminAPI
from fncli.k8s import get_k8s_secret

logger = logging.getLogger("secret")

# What a git secret holds until init-git-secret writes a real token into it.
GIT_PLACEHOLDER = {"TOKEN": "unset"}


def init_git_secret(
    config: RepoConfig,
    gitea_api: GiteaAdminAPI | GithubAPI,
    backend_api: FncliBackendAPI,
    static_token: bool = False,
) -> str | None:
    """
    Store the credentials the backend mints the repo's git tokens from, and return a token that works
    now (None for a GitHub App, which fncli cannot mint a token for).
    - GitHub: APP_ID, INSTALLATION_ID and PRIVATE_KEY from GH_APP_ID, GH_INSTALLATION_ID and GH_PRIVATE_KEY,
      or else TOKEN from GH_TOKEN.
    - Gitea: CLIENT_ID, CLIENT_SECRET and REFRESH_TOKEN of an OAuth2 application authorised as the admin user,
      or with static_token a TOKEN, a fresh Gitea personal access token.
    """
    token = None
    if config.is_github and config.github_app_id:
        values = {
            "APP_ID": config.github_app_id,
            "INSTALLATION_ID": config.github_installation_id,
            "PRIVATE_KEY": config.github_private_key,
        }
    elif config.is_github:
        token = config.github_token
        values = {"TOKEN": token}
    elif static_token:
        token = gitea_api.replace_token(config.token_name, [config.token_scope])
        values = {"TOKEN": token}
    else:
        tokens = gitea_api.authorize_oauth_app(config.token_name)
        token = tokens["access_token"]
        values = {
            "CLIENT_ID": tokens["client_id"],
            "CLIENT_SECRET": tokens["client_secret"],
            "REFRESH_TOKEN": tokens["refresh_token"],
        }
    secret = backend_api.upsert_secret(config.secret_label, values)
    for key, value in values.items():
        stored = get_k8s_secret(secret_name=secret["key"], namespace=secret["namespace"], key=key)
        if stored != value:
            raise RuntimeError(f"Secret {secret['key']} in {secret['namespace']} does not hold the new {key}")
    logger.info(
        f"Secret {config.secret_label} is {secret['key']} "
        f"in namespace {secret['namespace']} and holds {', '.join(values)} "
        f"(Gitea application or token {config.token_name!r}, scope {config.token_scope})"
    )
    return token


def get_git_token(entity: str, config: RepoConfig, backend_api: FncliBackendAPI) -> str:
    """A token the backend mints for the repo's global record from whatever its secret holds, as Dagster gets it."""
    find = backend_api.find_trigger_repository if entity == "trigger" else backend_api.find_results_repository
    repository = find(config.repo_uri)
    if repository is None:
        raise click.ClickException(
            f"Backend {entity} repository {config.repo_uri} does not exist (run init-backend-{entity}-repo first)"
        )
    return backend_api.get_repository_token(entity, repository.id).token


def verify_gitea_accepts_bearer_token(config: RepoConfig, token: str, gitea_repo: dict):
    """Raises if Gitea rejects the token, as the sensor would when it polls."""
    if config.is_github:
        branch = GithubAPI(GithubClient(token)).get_default_branch(gitea_repo["full_name"])
        logger.info(f"GitHub accepted the token: {gitea_repo['full_name']} (default branch {branch})")
        return
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
@click.option(
    "--static-token",
    is_flag=True,
    help="Gitea: store a personal access token (TOKEN) instead of OAuth2 credentials.",
)
@backend_source_options
def init_git_secret_command(entity, static_token, from_backend, project):
    """
    Store the credentials the backend mints a repo's git tokens from in its K8s secret. Gitea: an
    OAuth2 application, authorised without a browser. GitHub: a GitHub App if GH_APP_ID is set, else GH_TOKEN.
    """
    config = load_repo_config(entity, from_backend, project)
    init_git_secret(
        config=config,
        gitea_api=build_git_api(config),
        backend_api=build_backend_api(config),
        static_token=static_token,
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
    """Check the backend can mint a token from the repo's secret and the provider accepts it."""
    config = load_repo_config(entity, from_backend, project)
    gitea_repo = init_gitea_repo(config, build_git_api(config))
    token = get_git_token(entity, config, build_backend_api(config))
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
    """Delete the Gitea token and OAuth2 application (with the tokens it issued) that init-git-secret created for a repo."""
    config = load_repo_config(entity, from_backend, project)
    if config.is_github:
        logger.info("Not deleting the GitHub credentials: they are GH_TOKEN or the GitHub App, not ones fncli minted")
        return
    gitea_api = build_git_api(config)
    if gitea_api.delete_token(config.token_name):
        logger.info(f"Deleted Gitea token {config.token_name!r}")
    else:
        logger.info(f"Gitea token {config.token_name!r} does not exist")
    if gitea_api.delete_oauth_app(config.token_name):
        logger.info(f"Deleted Gitea OAuth2 application {config.token_name!r}")
    else:
        logger.info(f"Gitea OAuth2 application {config.token_name!r} does not exist")


COMMANDS = [
    init_git_secret_command,
    init_dataset_secret_command,
    init_backend_secret_command,
    verify_git_secret_command,
    delete_secret_command,
    delete_gitea_token_command,
]
