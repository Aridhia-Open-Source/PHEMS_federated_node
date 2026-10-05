"""
Commands for the webserver Project. Deleting what is already gone is logged, not an error.
"""

import json
import logging

import click

from fncli.cmds.common import ProjectConfig, build_backend_api
from fncli.dagster.backend import BackendAPI
from fncli.dagster.models import Project

logger = logging.getLogger("project")


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


COMMANDS = [
    init_backend_project_command,
    delete_backend_project_command,
    project_healthcheck_command,
]
