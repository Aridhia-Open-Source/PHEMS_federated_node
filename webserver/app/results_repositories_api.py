"""
results repository endpoints, global: a project is linked to one under
/projects/<id>/repositories/results (see projects_api.py). Create, edit and delete are admin
only, and editing or deleting needs every project the repository is linked to locked and
drained.
- GET /global/repositories/results
- GET /global/repositories/results/<id>
- POST /global/repositories/results
- PATCH /global/repositories/results/<id>
- DELETE /global/repositories/results/<id>
- GET /global/repositories/results/<id>/healthcheck, see healthcheck_api.py
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.repository_uri import RepositoryPatchRequest, RepositoryRequest, RepositoryUriRequest
from app.dtos.results_repository import ResultsRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.project_lock import require_all_drained
from app.helpers.wrappers import auth
from app.models.git_provider import GitProvider
from app.models.results_repository import ResultsRepository
from app.models.secret import Secret

bp = Blueprint('results_repositories', __name__, url_prefix='/global/repositories/results')
session = db.session


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_repositories():
    """
    GET /global/repositories/results/ — list the repositories
    """
    return [ResultsRepositoryDTO.from_model(r).dump() for r in ResultsRepository.query.order_by(ResultsRepository.id)], HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['GET'])
def get_repository(repo_id):
    """
    GET /global/repositories/results/<id> — get a single repository
    """
    repo = ResultsRepository.get_by_id(repo_id)
    return ResultsRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['DELETE'])
@auth(scope='can_do_admin')
def delete_repository(repo_id):
    """
    DELETE /global/repositories/results/<id> — delete the repository and its links, once every
    project it is linked to is locked and drained. Refused while a task delivered to it.
    """
    repo = ResultsRepository.get_by_id(repo_id)
    assignments = list(repo.project_assignments)
    require_all_drained([a.project for a in assignments])
    try:
        for assignment in assignments:
            assignment.delete(False)
        repo.delete()
    except Exception as exc:
        session.rollback()
        raise InvalidRequest("Error while deleting the record") from exc
    return '', HTTPStatus.NO_CONTENT


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@auth(scope='can_do_admin')
def post_repository():
    """
    POST /global/repositories/results/ — create a new repository, linked to no project yet.
    """
    body = request.json or {}
    if "project_id" in body or "target_dir" in body:
        raise InvalidRequest(
            "project_id and target_dir are not accepted, results repositories are global. "
            "Link one with PUT /projects/<id>/repositories/results/<repository id>"
        )
    req = RepositoryRequest.parse(body)

    uri = RepositoryUriRequest.normalised(req.uri)
    secret = Secret.get_by_label(req.secret_label)

    try:
        repo = ResultsRepository(
            uri=uri,
            provider=req.provider,
            api_uri=req.api_uri or GitProvider(req.provider).default_api_uri(uri),
            secret_id=secret.id,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    if ResultsRepository.query.filter_by(uri=repo.uri).first():
        raise InvalidRequest(f"Results repository {repo.uri} already exists", code=HTTPStatus.CONFLICT)
    repo.add()

    return ResultsRepositoryDTO.from_model(repo).dump(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
@auth(scope='can_do_admin')
def patch_repository(repo_id):
    """
    PATCH /global/repositories/results/<id> — update repository. Every project it is linked to has
    to be locked and drained, except to rotate the credentials only.
    """
    repo = ResultsRepository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")
    unknown = set(body) - {'provider', 'api_uri', 'secret_label', 'enabled'}
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")
    req = RepositoryPatchRequest.parse(body)

    # Rotating the credentials only is exempt from the lock, the uri is not changed
    if set(body) != {'secret_label'}:
        require_all_drained([a.project for a in repo.project_assignments])

    if 'secret_label' in body:
        repo.secret_id = Secret.get_by_label(req.secret_label).id

    if 'enabled' in body:
        repo.enabled = req.enabled

    for field in ('provider', 'api_uri'):
        if field in body:
            try:
                setattr(repo, field, getattr(req, field))
            except ValueError as e:
                raise InvalidRequest(str(e))

    session.commit()
    return ResultsRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK
