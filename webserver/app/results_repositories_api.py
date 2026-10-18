"""
results repository endpoints, global: a project is linked to one under
/projects/<id>/repositories/results (see projects_api.py). Create, edit and delete are admin
only. Deleting, or turning one on or off (enabled), needs every project the repository is linked to locked and
drained; any other edit applies at once. A secret_label naming a disabled secret is a 400 on POST and PATCH.
- GET /global/repositories/results
- GET /global/repositories/results/<id>
- POST /global/repositories/results
- PATCH /global/repositories/results/<id>
- DELETE /global/repositories/results/<id>
- GET /global/repositories/results/<id>/healthcheck, see healthcheck_api.py
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.repository_uri import RepositoryPatchRequest, RepositoryRequest
from app.dtos.results_repository import ResultsRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.project_lock import require_all_drained, require_all_drained_if_enabled
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

    provider = GitProvider.get_by_request_id(req.provider_id)
    secret = Secret.get_enabled_by_label(req.secret_label)

    try:
        repo = ResultsRepository(
            provider_id=provider.id,
            repo_path=req.repo_path,
            secret_id=secret.id,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    if ResultsRepository.query.filter_by(provider_id=provider.id, repo_path=repo.repo_path).first():
        raise InvalidRequest(
            f"Results repository {provider.uri}/{repo.repo_path} already exists", code=HTTPStatus.CONFLICT
        )
    repo.add()

    return ResultsRepositoryDTO.from_model(repo).dump(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
@auth(scope='can_do_admin')
def patch_repository(repo_id):
    """
    PATCH /global/repositories/results/<id> — update repository. Only a change of enabled needs every
    project it is linked to locked and drained, any other edit applies at once (the tasks created
    before are pinned to the old setup and fail instead of running against the new one). A disabled secret cannot be
    named (400), unless it is the one already in use.
    """
    repo = ResultsRepository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")
    unknown = set(body) - {'provider_id', 'secret_label', 'enabled'}
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")
    req = RepositoryPatchRequest.parse(body)

    require_all_drained_if_enabled(body, [a.project for a in repo.project_assignments])

    if 'secret_label' in body:
        repo.secret_id = Secret.get_enabled_by_label(req.secret_label, repo.secret_id).id

    if 'enabled' in body:
        repo.enabled = req.enabled

    if 'provider_id' in body:
        provider = GitProvider.get_by_request_id(req.provider_id)
        if ResultsRepository.query.filter(
            ResultsRepository.provider_id == provider.id, ResultsRepository.repo_path == repo.repo_path, ResultsRepository.id != repo.id
        ).first():
            raise InvalidRequest(
                f"Results repository {provider.uri}/{repo.repo_path} already exists", code=HTTPStatus.CONFLICT
            )
        repo.provider_id = provider.id

    session.commit()
    return ResultsRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK
