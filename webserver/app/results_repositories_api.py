"""
results repository endpoints, global: a project is linked to one under
/projects/<id>/repositories/results (see projects_api.py). Create, edit and delete are admin
only. Deleting one is a soft delete, refused with a 409 naming the projects it is linked to unless ?force=true. A secret_label naming a disabled secret is a 400 on POST and PATCH.
- GET /global/repositories/results
- GET /global/repositories/results/<id>
- POST /global/repositories/results
- PATCH /global/repositories/results/<id>
- DELETE /global/repositories/results/<id>
- GET /global/repositories/results/<id>/healthcheck, see healthcheck_api.py
"""
from http import HTTPStatus

from flask import Blueprint, g, request

from app.dtos.repository_uri import RepositoryPatchRequest, RepositoryRequest
from app.dtos.results_repository import ResultsRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest, UnauthorizedError
from app.helpers.soft_delete import delete_global
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
    DELETE /global/repositories/%s/<id> — soft delete the repository. A 409 names the projects it is linked to, unless ?force=true, which also revokes and deletes their links.
    """
    repo = ResultsRepository.get_by_id(repo_id)
    delete_global(repo, repo.project_assignments)
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
    PATCH /global/repositories/results/<id> — update repository. The tasks created
    before are pinned to the old setup and fail instead of running against the new one. A disabled secret cannot be
    named (400), unless it is the one already in use. Enabling the repository is a 409 while its secret (the new one,
    if secret_label is also sent) is disabled or deleted. `revoked` (a boolean) withdraws the repository from every
    project at once, or restores it, and does not change `enabled`: see helpers/task_config.revoked_resources.
    """
    repo = ResultsRepository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")
    unknown = set(body) - {'provider_id', 'secret_label', 'enabled', 'revoked'}
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")
    req = RepositoryPatchRequest.parse(body)
    if 'revoked' in body and not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a results repository")

    secret = repo.secret
    if 'secret_label' in body:
        secret = Secret.get_enabled_by_label(req.secret_label, repo.secret_id)
    if 'enabled' in body and req.enabled:
        secret.require_usable()
    repo.secret_id = secret.id

    if 'enabled' in body:
        repo.enabled = req.enabled

    if 'revoked' in body:
        repo.revoked = req.revoked

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
