"""
Commands that take down what setup-project built. Each step is its own idempotent command
(what is already gone is logged, not an error); `teardown-project` runs them in order.
"""

import logging

import click

from fncli.cmds.init_repo import (
    SECRET_CONFIGS,
    DatasetConfig,
    ProjectConfig,
    ResultsRepoConfig,
    TriggerRepoConfig,
    build_backend_api,
    delete_gitea_repo_command,
    find_project,
)

logger = logging.getLogger("teardown")


@click.command("delete-backend-dataset")
def delete_backend_dataset_command():
    """Delete the dataset from the backend."""
    config = DatasetConfig()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    if project is None:
        return
    dataset = backend_api.find_dataset(config.dataset_name, project.id)
    if dataset is None:
        logger.info(f"Backend dataset {config.dataset_name} does not exist")
        return
    backend_api.delete_dataset(dataset.id)
    logger.info(f"Deleted backend dataset {dataset.name} ({dataset.id})")


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


@click.command("delete-backend-project")
def delete_backend_project_command():
    """Delete the project from the backend, with everything still under it."""
    config = ProjectConfig()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    if project is None:
        return
    backend_api.delete_project(project.id)
    logger.info(f"Deleted backend project {project.name} ({project.id})")


# Each step with the options it runs with. A secret goes after what uses it.
STEPS = [
    (delete_backend_dataset_command, {}),
    (delete_backend_results_repo_command, {}),
    (delete_backend_trigger_repo_command, {}),
    (delete_secret_command, {"role": "trigger"}),
    (delete_secret_command, {"role": "results"}),
    (delete_secret_command, {"role": "dataset"}),
    (delete_backend_project_command, {}),
    (delete_gitea_repo_command, {"role": "trigger"}),
    (delete_gitea_repo_command, {"role": "results"}),
]


@click.command("teardown-project")
@click.confirmation_option(
    "-y",
    "--yes",
    prompt="Delete the project, its secrets and both Gitea repos with all their pull requests?",
)
@click.pass_context
def teardown_project_command(ctx):
    """Delete the whole dev project, including both Gitea repos."""
    for step, options in STEPS:
        logger.info(f"=== {step.name} {options or ''} ===")
        ctx.invoke(step, **options)


COMMANDS = [
    delete_backend_dataset_command,
    delete_backend_results_repo_command,
    delete_backend_trigger_repo_command,
    delete_secret_command,
    delete_backend_project_command,
    teardown_project_command,
]
