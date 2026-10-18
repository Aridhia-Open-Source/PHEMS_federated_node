from http import HTTPStatus

from app.helpers.exceptions import InvalidRequest
from app.models.project import Project


def require_locked(project: Project):
    """Guards creating a project's results link: allowed only while the project is locked, otherwise a 409."""
    if not project.locked:
        raise InvalidRequest(f"Project {project.id} must be locked to change it", HTTPStatus.CONFLICT)
