"""
project endpoints:
- GET /projects
- GET /projects/<project_id>
- POST /projects
- PATCH /projects/<project_id>
- DELETE /projects/<project_id>
- GET /projects/<project_id>/healthcheck
- GET /projects/<project_id>/datasets
- POST /projects/<project_id>/datasets
- GET /projects/<project_id>/datasets/<assignment_id>
- PATCH /projects/<project_id>/datasets/<assignment_id>
- DELETE /projects/<project_id>/datasets/<assignment_id>
"""

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from flask import Blueprint, g, request

from app.helpers.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest, UnauthorizedError
from app.dtos.base import page_of
from app.dtos.dataset import ProjectDatasetDTO
from app.dtos.project import (
    HealthCheckDTO, ProjectDTO, ProjectHealthDTO, RepositoryHealthDTO, ResultsRepositoryHealthDTO
)
from app.helpers.project_lock import require_drained
from app.helpers.query_filters import parse_query_params
from app.helpers.wrappers import audit, auth
from app.models.dataset import Dataset
from app.models.git_provider import ConnectionStatus
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.task import Task


HEALTHCHECK_MAX_WORKERS = 8

bp = Blueprint('projects', __name__, url_prefix='/projects')


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_projects():
    """
    GET /projects endpoint.
    """
    return page_of(parse_query_params(Project, request.args.copy()), ProjectDTO), HTTPStatus.OK


@bp.route('/<int:project_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_by_id(project_id: int):
    """
    GET /projects/<project_id> endpoint.
    """
    project = Project.query.filter_by(id=project_id).one_or_none()
    if project is None:
        raise DBRecordNotFoundError("Project not found")
    return ProjectDTO.from_model(project).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def create_project():
    """
    POST /projects endpoint.
    """
    body = Project.validate(request.json)
    if Project.query.filter(Project.name == body["name"]).one_or_none():
        raise InvalidRequest(f"Project {body["name"]} already exists", HTTPStatus.CONFLICT)

    if not isinstance(body.get("enabled", False), bool):
        raise InvalidRequest("enabled must be a boolean")

    project = Project(**body)
    project.add()
    return {"id": project.id}, HTTPStatus.CREATED


@bp.route('/<int:project_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project(project_id: int):
    """
    PATCH /projects/<project_id> endpoint. Enables or disables the project, locks or unlocks
    it. Locking or unlocking is always allowed, any other change only once the project is
    locked and drained, see require_drained.
    """
    project = Project.get_by_id(project_id)

    body = request.json or {}
    fields = {"enabled", "locked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")

    if set(body) - {"locked"}:
        require_drained(project)
    for field in body:
        setattr(project, field, body[field])
    db.session.commit()
    return ProjectDTO.from_model(project).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project(project_id: int):
    """
    DELETE /projects/<project_id> endpoint. Deletes the project and everything under it:
    tasks, dataset assignments and repositories. Secrets and datasets belong to no project:
    they, and their stored values, are left alone.
    """
    # Hard delete for now, a soft delete option can come later. Keycloak entries of the
    # datasets are left behind, as with DELETE /datasets.
    project = Project.get_by_id(project_id)
    require_drained(project)

    # Dependency order: most of these foreign keys to the project are RESTRICT. The
    # triggers left after the repositories' pull requests (the API ones) go with the
    # project, through the database's ON DELETE CASCADE.
    try:
        for task in Task.query.filter_by(project_id=project.id):
            task.delete(False)
        # Only the project's grants go, the datasets themselves are global. Each takes the
        # project's default with it if it was the default.
        for assignment in list(project.dataset_assignments):
            assignment.delete(False)
        for repo in project.trigger_repositories:
            repo.delete(False)
        for repo in project.results_repositories:
            repo.delete(False)
        project.delete(False)
    except Exception as exc:
        db.session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc

    db.session.commit()
    return '', HTTPStatus.NO_CONTENT


@bp.route('/<int:project_id>/healthcheck', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def project_healthcheck(project_id: int):
    """
    GET /projects/<project_id>/healthcheck endpoint. Checks each trigger repository can be
    reached with its token, and reports its pull request count and the project's results
    repository. A failed check is reported in the body, still with a 200.
    """
    project = Project.get_by_id(project_id)

    # Tokens are read here, in the request; only the network calls run in the threads.
    trigger_repos = list(project.trigger_repositories)
    results_repo = project.get_results_repository()
    checks = [repo.prepare_connection_check() for repo in trigger_repos]
    if results_repo:
        checks.append(results_repo.prepare_connection_check())
    with ThreadPoolExecutor(max_workers=HEALTHCHECK_MAX_WORKERS) as executor:
        results = list(executor.map(lambda check: check(), checks))

    repositories = []
    for repo, check in zip(trigger_repos, results):
        repositories.append(RepositoryHealthDTO(
            id=repo.id,
            uri=repo.uri,
            provider=repo.provider,
            pr_count=PullRequestTrigger.query.filter_by(trigger_repository_id=repo.id).count(),
            status=check.status.value,
            health_check=HealthCheckDTO(
                message=check.message,
                status_code=check.status_code,
                latency_ms=check.latency_ms,
            ),
        ))

    results_health = None
    if results_repo:
        check = results[-1]
        results_health = ResultsRepositoryHealthDTO(
            id=results_repo.id,
            uri=results_repo.uri,
            owned_by_federated_node=results_repo.owned_by_federated_node,
            target_dir=results_repo.target_dir,
            status=check.status.value,
            health_check=HealthCheckDTO(
                message=check.message,
                status_code=check.status_code,
                latency_ms=check.latency_ms,
            ),
        )

    healthy = repositories and all(r.status == ConnectionStatus.OK for r in repositories) and (
        results_health is None or results_health.status == ConnectionStatus.OK
    )
    health = ProjectHealthDTO(
        id=project.id,
        name=project.name,
        enabled=project.enabled,
        status="ok" if healthy else "error",
        results_repository=results_health,
        trigger_repositories=repositories,
    )
    return health.dump(), HTTPStatus.OK


def _assignment(project_id: int, assignment_id: int) -> ProjectDataset:
    assignment = ProjectDataset.query.filter_by(id=assignment_id, project_id=project_id).one_or_none()
    if assignment is None:
        raise DBRecordNotFoundError(f"Dataset assignment {assignment_id} not found in project {project_id}")
    return assignment


@bp.route('/<int:project_id>/datasets', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def list_project_datasets(project_id: int):
    """
    GET /projects/<project_id>/datasets endpoint. The project's dataset assignments, inactive
    ones included with their flags.
    """
    Project.get_by_id(project_id)
    assignments = ProjectDataset.query.filter_by(project_id=project_id).order_by(ProjectDataset.id)
    return [ProjectDatasetDTO.from_model(a).dump() for a in assignments], HTTPStatus.OK


@bp.route('/<int:project_id>/datasets', methods=['POST'])
@audit
@auth(scope='can_admin_dataset')
def assign_project_dataset(project_id: int):
    """
    POST /projects/<project_id>/datasets endpoint. Assigns a global dataset to the project.
    The first one assigned becomes the project's default.
    Body: {"dataset_id": 1, "enabled": true}, enabled is optional.
    """
    project = Project.get_by_id(project_id)
    body = request.json or {}
    if not set(body) <= {"dataset_id", "enabled"} or not isinstance(body.get("dataset_id"), int):
        raise InvalidRequest("Provide dataset_id (an integer) and, optionally, enabled")
    if not isinstance(body.get("enabled", True), bool):
        raise InvalidRequest("enabled must be a boolean")
    dataset = Dataset.get_dataset_by_name_or_id(id=body["dataset_id"])
    if ProjectDataset.query.filter_by(project_id=project.id, dataset_id=dataset.id).one_or_none():
        raise InvalidRequest(
            f"Dataset {dataset.name} is already assigned to project {project.name}", HTTPStatus.CONFLICT
        )

    assignment = ProjectDataset(project.id, dataset.id, enabled=body.get("enabled", True))
    assignment.add()
    return ProjectDatasetDTO.from_model(assignment).dump(), HTTPStatus.CREATED


@bp.route('/<int:project_id>/datasets/<int:assignment_id>', methods=['GET'])
@audit
@auth(scope='can_admin_dataset')
def get_project_dataset(project_id: int, assignment_id: int):
    """
    GET /projects/<project_id>/datasets/<assignment_id> endpoint.
    """
    return ProjectDatasetDTO.from_model(_assignment(project_id, assignment_id)).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/datasets/<int:assignment_id>', methods=['PATCH'])
@audit
@auth(scope='can_admin_dataset')
def patch_project_dataset(project_id: int, assignment_id: int):
    """
    PATCH /projects/<project_id>/datasets/<assignment_id> endpoint. Turns the assignment on or
    off (enabled), which needs the project locked and drained, or revokes and re-grants it
    (revoked), which is admin only and takes effect at once.
    """
    assignment = _assignment(project_id, assignment_id)
    body = request.json or {}
    fields = {"enabled", "revoked"}
    if not body or not set(body) <= fields:
        raise InvalidRequest(f"Provide any of: {', '.join(sorted(fields))}")
    for field in body:
        if not isinstance(body[field], bool):
            raise InvalidRequest(f"{field} must be a boolean")
    if "revoked" in body and not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a dataset")

    if "enabled" in body:
        require_drained(assignment.project)
    for field in body:
        setattr(assignment, field, body[field])
    db.session.commit()
    return ProjectDatasetDTO.from_model(assignment).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>/datasets/<int:assignment_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project_dataset(project_id: int, assignment_id: int):
    """
    DELETE /projects/<project_id>/datasets/<assignment_id> endpoint. Removes the assignment,
    not the dataset, once the project is locked and drained. If it was the project's default,
    the project has none afterwards.
    """
    assignment = _assignment(project_id, assignment_id)
    require_drained(assignment.project)
    assignment.delete()
    return '', HTTPStatus.NO_CONTENT
