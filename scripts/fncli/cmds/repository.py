"""
Commands for the two Gitea repos (the trigger repo the sensor watches and the results repo
tasks write to) and their records in the backend.
"""

import logging

import click

from fncli.cmds.common import (
    ROLE_CONFIGS,
    RepoConfig,
    ResultsRepoConfig,
    TriggerRepoConfig,
    build_backend_api,
    build_gitea_api,
    role_option,
)
from fncli.cmds.project import find_project, init_backend_project
from fncli.dagster.backend import BackendAPI
from fncli.dagster.gitea import GiteaAdminAPI
from fncli.dagster.models import Project, ResultsRepository, TriggerRepository

logger = logging.getLogger("repository")


def init_gitea_repo(config: RepoConfig, gitea_api: GiteaAdminAPI) -> dict:
    gitea_repo = gitea_api.get_or_create_repo(config.repo, "Trigger-repository simulation")
    logger.info(f"Gitea repo: {gitea_repo['html_url']} (default branch {gitea_repo['default_branch']})")
    return gitea_repo


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


@click.command("init-gitea-repo")
@role_option
def init_gitea_repo_command(role):
    """Find or create a repo in Gitea."""
    config = ROLE_CONFIGS[role]()
    init_gitea_repo(config, build_gitea_api(config))


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


@click.command("delete-backend-trigger-repo")
def delete_backend_trigger_repo_command():
    """Delete the trigger repository from the backend, with its pull requests."""
    config = TriggerRepoConfig()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    if project is None:
        return
    repo = backend_api.find_repository(config.repo_uri, project.id)
    if repo is None:
        logger.info(f"Backend trigger repository {config.repo_uri} does not exist")
        return
    backend_api.delete_repository(repo.id)
    logger.info(f"Deleted backend trigger repository {repo.uri} ({repo.id})")


@click.command("delete-backend-results-repo")
def delete_backend_results_repo_command():
    """Delete the results repository from the backend."""
    config = ResultsRepoConfig()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    if project is None:
        return
    repos = backend_api.get_results_repositories(project.id)
    if not repos:
        logger.info(f"Project {project.id} has no backend results repository")
    for repo in repos:
        backend_api.delete_results_repository(repo.id)
        logger.info(f"Deleted backend results repository {repo.uri} ({repo.id})")


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
    delete_gitea_repo_command,
    init_backend_trigger_repo_command,
    init_backend_results_repo_command,
    delete_backend_trigger_repo_command,
    delete_backend_results_repo_command,
]
