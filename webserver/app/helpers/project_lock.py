from http import HTTPStatus

from app.helpers.exceptions import InvalidRequest
from app.models.project import Project


def require_drained(project: Project):
    """
    Guards a change to the project or what is under it: allowed only while the project is
    locked and nothing of it is in flight, otherwise a 409.
    """
    if not project.locked:
        raise InvalidRequest(f"Project {project.id} must be locked to change it", HTTPStatus.CONFLICT)
    in_flight = project.in_flight_task_ids()
    if in_flight:
        error = InvalidRequest(f"Project {project.id} has tasks in flight", HTTPStatus.CONFLICT)
        error.extra_fields = in_flight
        raise error


def require_all_drained(projects: list[Project]):
    """
    Guards a change to a global resource every one of the projects uses: each of them has to
    be locked and drained, otherwise a 409 naming the first that is not.
    """
    for project in projects:
        require_drained(project)
