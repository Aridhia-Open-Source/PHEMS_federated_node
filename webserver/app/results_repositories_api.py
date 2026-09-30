"""
results repository endpoints:
- GET /results_repositories
- GET /results_repositories/<id>
- POST /results_repositories
- PATCH /results_repositories/<id>
- DELETE /results_repositories/<id>
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.results_repository import ResultsRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.repository_loop import check_no_loop
from app.helpers.wrappers import auth
from app.models.k8s_secret import K8sSecret
from app.models.project import Project
from app.models.results_repository import ResultsRepository

bp = Blueprint('results_repositories', __name__, url_prefix='/results_repositories')
session = db.session


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_repositories():
    """
    GET /results_repositories/ — list repositories, optionally of one project (?project_id=)
    """
    query = ResultsRepository.query
    project_id = request.args.get('project_id', type=int)
    if project_id is not None:
        query = query.filter_by(project_id=project_id)
    return [ResultsRepositoryDTO.from_model(r).dump() for r in query.all()], HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['GET'])
def get_repository(repo_id):
    """
    GET /results_repositories/<id> — get a single repository
    """
    repo = ResultsRepository.get_by_id(repo_id)
    return ResultsRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['DELETE'])
def delete_repository(repo_id):
    """
    DELETE /results_repositories/<id> — delete a single repository
    """
    repo = ResultsRepository.get_by_id(repo_id)
    repo.delete()
    return '', HTTPStatus.NO_CONTENT


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
def post_repository():
    """
    POST /results_repositories/ — create a new repository. A project has one.
    """
    body = request.json or {}
    for field in ('uri', 'project_id', 'provider', 'api_uri', 'k8s_secret_name', 'target_dir'):
        if not body.get(field):
            raise InvalidRequest(f"{field} is required")

    # Validate project and secret exist
    Project.get_by_id(body['project_id'])
    secret = K8sSecret.get_in_project(body['project_id'], body['k8s_secret_name'])

    if ResultsRepository.query.filter_by(project_id=body['project_id']).first():
        raise InvalidRequest(
            f"Project {body['project_id']} already has a results repository",
            code=HTTPStatus.CONFLICT
        )

    try:
        repo = ResultsRepository(
            uri=ResultsRepository.parse_repo_uri(body['uri']),
            provider=body['provider'],
            api_uri=body['api_uri'],
            k8s_secret_id=secret.id,
            target_dir=body['target_dir'],
            project_id=body['project_id'],
            owned_by_federated_node=body.get('owned_by_federated_node', True),
            repo_path=body.get('repo_path'),
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    repo.add(commit=False)
    try:
        check_no_loop(repo.project_id, repo.uri)
    except InvalidRequest:
        session.rollback()
        raise
    session.commit()

    return ResultsRepositoryDTO.from_model(repo).dump(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
def patch_repository(repo_id):
    """
    PATCH /results_repositories/<id> — update repository
    """
    repo = ResultsRepository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")

    if 'project_id' in body:
        Project.get_by_id(body['project_id'])
        repo.project_id = body['project_id']

    if 'target_dir' in body:
        if not body['target_dir']:
            raise InvalidRequest("target_dir cannot be empty")
        repo.target_dir = body['target_dir']

    if 'k8s_secret_name' in body:
        if not body['k8s_secret_name']:
            raise InvalidRequest("k8s_secret_name cannot be empty")
        repo.k8s_secret_id = K8sSecret.get_in_project(repo.project_id, body['k8s_secret_name']).id

    if 'owned_by_federated_node' in body:
        repo.owned_by_federated_node = body['owned_by_federated_node']

    for field in ('provider', 'api_uri'):
        if field in body:
            if not body[field]:
                raise InvalidRequest(f"{field} cannot be empty")
            try:
                setattr(repo, field, body[field])
            except ValueError as e:
                raise InvalidRequest(str(e))

    session.flush()
    try:
        check_no_loop(repo.project_id, repo.uri)
    except InvalidRequest:
        session.rollback()
        raise
    session.commit()
    return ResultsRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK
