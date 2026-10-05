"""
project endpoints:
- GET /projects
- GET /projects/<project_id>
- POST /projects
- PATCH /projects/<project_id>
- DELETE /projects/<project_id>
- GET /projects/<project_id>/healthcheck
"""

from http import HTTPStatus
from flask import Blueprint, request

from app.helpers.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.dtos.base import page_of
from app.dtos.project import (
    HealthCheckDTO, ProjectDTO, ProjectHealthDTO, RepositoryHealthDTO, ResultsRepositoryHealthDTO
)
from app.helpers.query_filters import parse_query_params
from app.helpers.wrappers import audit, auth
from app.models.extras.request import Request
from app.models.git_provider import ConnectionStatus
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.secret import Secret
from app.models.task import Task
from app.secrets_api import SecretProvider


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
    PATCH /projects/<project_id> endpoint. Enables or disables the project.
    """
    project = Project.get_by_id(project_id)

    body = request.json or {}
    if "enabled" not in body:
        raise InvalidRequest("No fields provided to update")
    if not isinstance(body["enabled"], bool):
        raise InvalidRequest("enabled must be a boolean")

    project.enabled = body["enabled"]
    db.session.commit()
    return ProjectDTO.from_model(project).dump(), HTTPStatus.OK


@bp.route('/<int:project_id>', methods=['DELETE'])
@audit
@auth(scope='can_admin_dataset')
def delete_project(project_id: int):
    """
    DELETE /projects/<project_id> endpoint. Deletes the project and everything under it:
    tasks, requests, datasets, repositories and secrets. The stored secret values go after
    the database commit.
    """
    # Hard delete for now, a soft delete option can come later. Keycloak entries of the
    # datasets are left behind, as with DELETE /datasets.
    project = Project.get_by_id(project_id)
    project_secrets = Secret.query.filter_by(project_id=project.id).all()
    secrets = [(s.provider, s.key, s.namespace) for s in project_secrets]

    # Dependency order: most of these foreign keys to the project are RESTRICT.
    try:
        for task in Task.query.filter_by(project_id=project.id):
            task.delete(False)
        for request_ in Request.query.filter_by(project_id=project.id):
            request_.delete(False)
        for dataset in project.datasets:
            dataset.delete(False)
        for repo in project.trigger_repositories:
            repo.delete(False)
        for repo in project.results_repositories:
            repo.delete(False)
        for secret in project_secrets:
            secret.delete(False)
        project.delete(False)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc

    for provider, key, namespace in secrets:
        SecretProvider(provider).delete(key, namespace)
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

    repositories = []
    for repo in project.trigger_repositories:
        check = repo.check_connection()
        repositories.append(RepositoryHealthDTO(
            id=repo.id,
            uri=repo.uri,
            provider=repo.provider,
            pr_count=PullRequest.query.filter_by(trigger_repository_id=repo.id).count(),
            status=check.status.value,
            health_check=HealthCheckDTO(
                message=check.message,
                status_code=check.status_code,
                latency_ms=check.latency_ms,
            ),
        ))

    results_repo = project.get_results_repository()
    results_health = None
    if results_repo:
        check = results_repo.check_connection()
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
