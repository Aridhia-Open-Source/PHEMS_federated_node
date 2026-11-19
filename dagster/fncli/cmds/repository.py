"""
The two Gitea repos (the trigger repo the sensor watches and the results repo tasks write to) and their records in the
backend, as the simulation (cmds/simulate.py) sets them up, and what the commands that read them from the backend use.
The node's own are made by `fncli apply`.
"""

import logging

import click

from fncli.cmds.common import ENTITY_CONFIGS, RepoConfig, ResultsRepoConfig, TriggerRepoConfig
from fncli.backend import FncliBackendAPI
from fncli.cmds.nodefile import step_target
from app.git_uri import normalise_repo_uri
from fncli.gitea import GiteaAdminAPI
from app.models import GitProvider, Project, ProjectResultsRepository, ProjectTriggerRepository
from fncli.nodefile.loader import Context

logger = logging.getLogger("repository")


def init_gitea_repo(config: RepoConfig, gitea_api: GiteaAdminAPI) -> dict:
    """Find or create the repo as the Gitea admin user."""
    gitea_repo = gitea_api.get_or_create_repo(config.repo, "Trigger-repository simulation")
    logger.info(f"Gitea repo: {gitea_repo['html_url']} (default branch {gitea_repo['default_branch']})")
    return gitea_repo


def init_backend_provider(config: RepoConfig, backend_api: FncliBackendAPI) -> GitProvider:
    """The backend's git provider for the host the repo is on, shared by both repos and every project."""
    return backend_api.get_or_create_git_provider(
        uri=config.provider_uri,
        name=f"{config.git_provider}-{config.provider_uri.split('://')[1]}",
        type=config.git_provider,
        api_uri=config.provider_api_uri,
    )


def init_backend_trigger_repo(
    config: TriggerRepoConfig, backend_api: FncliBackendAPI, project: Project, base_branch: str
) -> ProjectTriggerRepository:
    provider = init_backend_provider(config, backend_api)
    repo = backend_api.get_or_create_trigger_repository(
        uri=config.repo_uri,
        provider_id=provider.id,
        secret_label=config.secret_label,
    )
    assignment = backend_api.get_or_assign_repository(
        project.id, repo, watch_dir=config.watch_dir, base_branch=base_branch
    )
    logger.info(
        f"Backend trigger repository {repo.id}: {repo.uri} "
        f"(provider {repo.provider.name}, api_uri {repo.provider.api_uri}, secret {repo.secret.label}), "
        f"assigned to project {assignment.project_id} (branch {assignment.base_branch}, "
        f"watch_dir {assignment.watch_dir}, pr_cursor {assignment.pr_cursor})"
    )
    return assignment


def init_backend_results_repo(
    config: ResultsRepoConfig, backend_api: FncliBackendAPI, project: Project, base_branch: str
) -> ProjectResultsRepository:
    provider = init_backend_provider(config, backend_api)
    repo = backend_api.get_or_create_results_repository(
        uri=config.repo_uri,
        provider_id=provider.id,
        secret_label=config.secret_label,
    )
    assignment = backend_api.get_or_assign_results_repository(project.id, repo, config.target_dir, base_branch)
    logger.info(
        f"Backend results repository {repo.id}: {repo.uri} "
        f"(provider {repo.provider.name}, api_uri {repo.provider.api_uri}, secret {repo.secret.label}), "
        f"assigned to project {assignment.project_id} (branch {assignment.base_branch}, target_dir {assignment.target_dir})"
    )
    return assignment


def get_backend_repo_record(entity: str, backend_api: FncliBackendAPI, project: Project):
    """The project's one trigger or results repository assignment."""
    if entity == "trigger":
        records = backend_api.get_project_trigger_repositories(project.id)
    else:
        records = backend_api.get_project_results_repositories(project.id)
    if len(records) != 1:
        raise click.ClickException(
            f"Project {project.name} has {len(records)} backend {entity} repositories, "
            f"expected 1 (run fncli apply first)"
        )
    return records[0]


def load_repo_config(entity: str, context: Context, project: str, backend_api: FncliBackendAPI) -> RepoConfig:
    """
    The config of the project's trigger or results repository, from its record on the node. The repository must be
    under the Gitea admin user, if it is on Gitea.
    """
    backend_project = backend_api.find_project(project)
    if backend_project is None:
        raise click.ClickException(f"Project {project} not found in the backend (run fncli apply first)")
    record = get_backend_repo_record(entity, backend_api, backend_project)
    # A record is the project's assignment, with the repository nested
    repository = record.trigger_repository if entity == "trigger" else record.results_repository
    owner, name = normalise_repo_uri(repository.uri).split("/")[-2:]
    own_field = {"watch_dir": record.watch_dir} if entity == "trigger" else {"target_dir": record.target_dir}
    config = ENTITY_CONFIGS[entity](
        **own_field,
        node=context.node,
        base_branch=record.base_branch,
        project_name=backend_project.name,
        repo=name,
        repo_uri=repository.uri,
        gitea_url=repository.provider.uri,
        gitea_api_uri=repository.provider.api_uri,
        backend_secret_label=repository.secret.label,
        backend_provider_type=repository.provider.type,
    )
    if not config.is_github and owner != config.gitea_admin_user:
        raise click.ClickException(
            f"Backend {entity} repository {repository.uri} is owned by {owner}, not the Gitea "
            f"admin user {config.gitea_admin_user}: it is not a repo this tool can manage"
        )
    return config


def step_repo_config(entity: str, context: Context, project: str | None) -> RepoConfig:
    """For a step command: the config of the project's trigger or results repository, read from the node"""
    name, backend_api = step_target(context, project)
    return load_repo_config(entity, context, name, backend_api)
