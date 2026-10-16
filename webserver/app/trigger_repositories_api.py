"""
trigger repository endpoints, global: a project is assigned to one under
/projects/<id>/trigger_repositories (see project_trigger_repositories_api.py). Create, edit and delete are admin
only, and editing or deleting needs every project the repository is assigned to locked and
drained.
- GET /trigger_repositories
- GET /trigger_repositories/<id>
- POST /trigger_repositories
- PATCH /trigger_repositories/<id>
- DELETE /trigger_repositories/<id>
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.repository_uri import RepositoryUriRequest
from app.dtos.trigger_repository import TriggerRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.project_lock import require_all_drained
from app.helpers.wrappers import auth
from app.models.git_provider import GitProvider
from app.models.trigger_repository import TriggerRepository
from app.models.secret import Secret

bp = Blueprint('trigger_repositories', __name__, url_prefix='/trigger_repositories')
session = db.session


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_repositories():
    """
    GET /trigger_repositories/ — list the repositories
    """
    return [TriggerRepositoryDTO.from_model(r).dump() for r in TriggerRepository.query.order_by(TriggerRepository.id)], HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['GET'])
def get_repository(repo_id):
    """
    GET /trigger_repositories/<id> — get a single repository
    """
    repo = TriggerRepository.get_by_id(repo_id)
    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['DELETE'])
@auth(scope='can_do_admin', check_dataset=False)
def delete_repository(repo_id):
    """
    DELETE /trigger_repositories/<id> — delete the repository and its assignments, once every
    project it is assigned to is locked and drained. Refused while a pull request of it has been ingested.
    """
    repo = TriggerRepository.get_by_id(repo_id)
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
@auth(scope='can_do_admin', check_dataset=False)
def post_repository():
    """
    POST /trigger_repositories/ — create a new repository, assigned to no project yet.
    """
    body = request.json or {}
    if "project_id" in body or "watch_dir" in body or "base_branch" in body or "initial_cursor" in body:
        raise InvalidRequest(
            "project_id, watch_dir, base_branch and initial_cursor are not accepted, trigger "
            "repositories are global. Assign one with POST /projects/<id>/trigger_repositories"
        )
    for field in ('uri', 'provider', 'secret_label'):
        if not body.get(field):
            raise InvalidRequest(f"{field} is required")

    uri = RepositoryUriRequest.normalised(body['uri'])
    secret = Secret.get_by_label(body['secret_label'])

    try:
        repo = TriggerRepository(
            uri=uri,
            provider=body['provider'],
            api_uri=body.get('api_uri') or GitProvider(body['provider']).default_api_uri(uri),
            secret_id=secret.id,
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    if TriggerRepository.query.filter_by(uri=repo.uri).first():
        raise InvalidRequest(f"Trigger repository {repo.uri} already exists", code=HTTPStatus.CONFLICT)
    repo.add()

    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
@auth(scope='can_do_admin', check_dataset=False)
def patch_repository(repo_id):
    """
    PATCH /trigger_repositories/<id> — update repository. Every project it is assigned to has
    to be locked and drained, except to rotate the credentials only.
    """
    repo = TriggerRepository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")
    unknown = set(body) - {'provider', 'api_uri', 'secret_label'}
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")

    # Rotating the credentials only is exempt from the lock, the uri is not changed
    if set(body) != {'secret_label'}:
        require_all_drained([a.project for a in repo.project_assignments])

    if 'secret_label' in body:
        if not body['secret_label']:
            raise InvalidRequest("secret_label cannot be empty")
        repo.secret_id = Secret.get_by_label(body['secret_label']).id

    for field in ('provider', 'api_uri'):
        if field in body:
            if not body[field]:
                raise InvalidRequest(f"{field} cannot be empty")
            try:
                setattr(repo, field, body[field])
            except ValueError as e:
                raise InvalidRequest(str(e))

    session.commit()
    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK
