"""
Commands for the nexus-api Project. Its datasets and repositories are global, the project only holds assignments of them. Deleting what is already gone is logged, not an error.
"""

import json
import logging

import click

from fncli.cmds.common import ProjectConfig, build_backend_api
from fncli.backend import FncliBackendAPI
from app.models import Project

logger = logging.getLogger("project")


def init_backend_project(config: ProjectConfig, backend_api: FncliBackendAPI) -> Project:
    """
    Find or create the project, disabled when new: a results repository can only be assigned to a
    disabled project. Enable it once its resources are set up (project-set --enabled true).
    """
    project = backend_api.get_or_create_project(
        name=config.project_name,
        description="Trigger-repository simulation",
    )
    logger.info(f"Backend project: {project.name} (id {project.id}, enabled {project.enabled})")
    return project


def find_project(config: ProjectConfig, backend_api: FncliBackendAPI) -> Project | None:
    """For the delete steps: a project that is already gone is not an error."""
    project = backend_api.find_project(config.project_name)
    if project is None:
        logger.info(f"Backend project {config.project_name} does not exist")
    return project


@click.command("init-backend-project")
def init_backend_project_command():
    """Find or create the test project in the backend, disabled when new."""
    config = ProjectConfig()
    init_backend_project(config, build_backend_api(config))


@click.command("delete-backend-project")
def delete_backend_project_command():
    """Delete the project from the backend, with its assignments. Global datasets, repositories and secrets stay."""
    config = ProjectConfig()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    if project is None:
        return
    backend_api.delete_project(project.id)
    logger.info(f"Deleted backend project {project.name} ({project.id})")


def get_project_healthcheck(config: ProjectConfig, backend_api: FncliBackendAPI) -> dict:
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


COMMANDS = [
    init_backend_project_command,
    delete_backend_project_command,
    project_healthcheck_command,
]
