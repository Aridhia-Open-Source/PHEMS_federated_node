from http import HTTPStatus

from app.helpers.exceptions import InvalidRequest
from app.models.project import Project


def require_disabled(project: Project):
    """Guards creating a project's results link: allowed only while the project is disabled, otherwise a 409."""
    if project.enabled:
        raise InvalidRequest(
            f"Project {project.id} must be disabled to link a results repository", HTTPStatus.CONFLICT
        )
