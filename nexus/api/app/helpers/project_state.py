from http import HTTPStatus

from app.helpers.exceptions import InvalidRequest
from app.models.project import Project


def require_disabled(project: Project):
    """Guards creating a project's results resource: allowed only while the project is disabled, otherwise a 409."""
    if project.enabled:
        raise InvalidRequest(
            f"Project {project.id} must be disabled to assign a results repository", HTTPStatus.CONFLICT
        )


def require_accepts_tasks(project: Project):
    """Guards creating a task, from a pull request or through the API: a disabled or revoked project accepts none, a 409."""
    if not project.enabled:
        raise InvalidRequest(f"Project '{project.name}' is disabled", HTTPStatus.CONFLICT)
    if project.revoked:
        raise InvalidRequest(f"Project {project.id} is revoked", HTTPStatus.CONFLICT)
