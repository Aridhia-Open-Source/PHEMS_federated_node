"""
Commands for the webserver Project, and the two that run every step of the dev project in
order: `setup-project` builds it and `teardown-project` takes it down again. Each step is
its own idempotent command (what is already gone is logged, not an error).
"""

import json
import logging

import click

from fncli.cmds.common import (
    ProjectConfig,
    build_backend_api,
    find_project,
    init_backend_project,
)
from fncli.cmds.dataset import delete_backend_dataset_command, init_backend_dataset_command
from fncli.cmds.repository import (
    delete_backend_results_repo_command,
    delete_backend_trigger_repo_command,
    delete_gitea_repo_command,
    init_backend_results_repo_command,
    init_backend_trigger_repo_command,
    init_gitea_repo_command,
)
from fncli.cmds.secret import (
    delete_secret_command,
    init_dataset_secret_command,
    init_git_secret_command,
    verify_git_secret_command,
)
from fncli.dagster.backend import BackendAPI

logger = logging.getLogger("project")


@click.command("init-backend-project")
def init_backend_project_command():
    """Find or create the test project in the backend, and enable it."""
    config = ProjectConfig()
    init_backend_project(config, build_backend_api(config))


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
SETUP_STEPS = [
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
    for step, options in SETUP_STEPS:
        logger.info(f"=== {step.name} {options or ''} ===")
        ctx.invoke(step, **options)


# Each step with the options it runs with. A secret goes after what uses it.
TEARDOWN_STEPS = [
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
    for step, options in TEARDOWN_STEPS:
        logger.info(f"=== {step.name} {options or ''} ===")
        ctx.invoke(step, **options)


COMMANDS = [
    init_backend_project_command,
    delete_backend_project_command,
    project_healthcheck_command,
    setup_project_command,
    teardown_project_command,
]
