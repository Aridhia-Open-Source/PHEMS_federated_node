"""
The nexus-api Project and its healthcheck. Its datasets and repositories are global, the project only holds
assignments of them. It is made and deleted by `fncli apply` and `fncli delete`.
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
    """The config's project, or None, which is logged: not an error for every caller."""
    project = backend_api.find_project(config.project_name)
    if project is None:
        logger.info(f"Backend project {config.project_name} does not exist")
    return project


def get_project_healthcheck(config: ProjectConfig, backend_api: FncliBackendAPI) -> dict:
    project = backend_api.find_project(config.project_name)
    if project is None:
        raise click.ClickException(
            f"Project {config.project_name} not found, run fncli apply first"
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


COMMANDS = [project_healthcheck_command]
