"""
trigger repository endpoints, global: a project is linked to one under
/projects/<id>/repositories/triggers (see project_trigger_repositories_api.py). Create, edit and delete are admin
only, and editing or deleting needs every project the repository is linked to locked and
drained.
- GET /global/repositories/triggers
- GET /global/repositories/triggers/<id>
- POST /global/repositories/triggers
- PATCH /global/repositories/triggers/<id>
- DELETE /global/repositories/triggers/<id>
- GET /global/repositories/triggers/<id>/pull_requests
- POST /global/repositories/triggers/<id>/pull_requests
- GET /global/repositories/triggers/<id>/healthcheck, see healthcheck_api.py
"""
from http import HTTPStatus

import sqlalchemy as sa
from flask import Blueprint, request

from app.dtos.repository_uri import RepositoryUriRequest
from app.dtos.trigger_repository import PullRequestDTO, PullRequestRequest, TriggerRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.query_filters import arg_get
from app.helpers.project_lock import require_all_drained
from app.helpers.pull_request_fanout import ingest_pull_requests
from app.helpers.wrappers import auth
from app.models.git_provider import GitProvider
from app.models.project import Project
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request import PullRequest
from app.models.trigger_repository import TriggerRepository
from app.models.secret import Secret

bp = Blueprint('trigger_repositories', __name__, url_prefix='/global/repositories/triggers')
session = db.session


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_repositories():
    """
    GET /global/repositories/triggers/ — list the repositories. With ?active_link=true only those with an
    active link (enabled and not revoked) of an enabled project, and only enabled repositories, which is
    what Dagster polls.
    """
    query = TriggerRepository.query
    if request.args.get('active_link', '').lower() == 'true':
        query = query.filter(TriggerRepository.enabled.is_(True), TriggerRepository.project_assignments.any(sa.and_(
            ProjectTriggerRepository.enabled.is_(True),
            ProjectTriggerRepository.revoked.is_(False),
            ProjectTriggerRepository.project.has(Project.enabled.is_(True)),
        )))
    return [TriggerRepositoryDTO.from_model(r).dump() for r in query.order_by(TriggerRepository.id)], HTTPStatus.OK


@bp.route('/<int:repo_id>', methods=['GET'])
def get_repository(repo_id):
    """
    GET /global/repositories/triggers/<id> — get a single repository
    """
    repo = TriggerRepository.get_by_id(repo_id)
    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK


@bp.route('/<int:repo_id>/pull_requests', methods=['GET'])
def get_pull_requests(repo_id):
    """
    GET /global/repositories/triggers/<id>/pull_requests — the provider's facts of the pull requests
    stored for the repository, most recent merge first.
    Query params: page (default 1), per_page (default 20)
    """
    TriggerRepository.get_by_id(repo_id)
    page = arg_get('page', 1, type=int)
    per_page = arg_get('per_page', 20, type=int)
    paginated = PullRequest.query.filter_by(trigger_repository_id=repo_id)\
        .order_by(PullRequest.merged_at.desc(), PullRequest.number.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items': [PullRequestDTO.from_model(pr).dump() for pr in paginated.items],
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
    }, HTTPStatus.OK


# TODO: called by Dagster only, like the per-project pull request routes
@bp.route('/<int:repo_id>/pull_requests', methods=['POST'])
def post_pull_requests_batch(repo_id):
    """
    POST /global/repositories/triggers/<id>/pull_requests — store up to 100 pull requests of the
    repository and create their triggers for every active assignment. Idempotent: a number
    already stored is left as it is. Refused for a disabled repository, which stores nothing.
    Responds with the numbers stored and those already there.
    Body: {"pull_requests": [pull requests, see PullRequestRequest]}
    """
    repo = TriggerRepository.get_by_id(repo_id)
    if not repo.enabled:
        raise InvalidRequest(f"Trigger repository {repo.uri} is disabled")
    body = (request.json or {}).get('pull_requests')
    if not isinstance(body, list):
        raise InvalidRequest("pull_requests must be a list of pull requests")
    # Claude (issue 1): the cap is fine; the Dagster ingest sensor must chunk its posts.
    # One invalid PR (PullRequestRequest.parse) also refuses the whole batch.
    if len(body) > 100:
        raise InvalidRequest("Maximum 100 pull requests per batch")

    created, existing = ingest_pull_requests(repo.id, [PullRequestRequest.parse(pr) for pr in body])
    session.commit()
    return {
        'created': [pr.number for pr in created],
        'existing': [pr.number for pr in existing],
    }, HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['DELETE'])
@auth(scope='can_do_admin')
def delete_repository(repo_id):
    """
    DELETE /global/repositories/triggers/<id> — delete the repository and its links, once every
    project it is linked to is locked and drained. Refused while a pull request of it has been ingested.
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
@auth(scope='can_do_admin')
def post_repository():
    """
    POST /global/repositories/triggers/ — create a new repository, linked to no project yet.
    """
    body = request.json or {}
    if "project_id" in body or "watch_dir" in body or "base_branch" in body:
        raise InvalidRequest(
            "project_id, watch_dir and base_branch are not accepted, trigger "
            "repositories are global. Link one with PUT /projects/<id>/repositories/triggers/<repository id>"
        )
    for field in ('uri', 'provider', 'secret_label'):
        if not body.get(field):
            raise InvalidRequest(f"{field} is required")

    if not isinstance(body.get("enabled", True), bool):
        raise InvalidRequest("enabled must be a boolean")

    uri = RepositoryUriRequest.normalised(body['uri'])
    secret = Secret.get_by_label(body['secret_label'])

    try:
        repo = TriggerRepository(
            uri=uri,
            provider=body['provider'],
            api_uri=body.get('api_uri') or GitProvider(body['provider']).default_api_uri(uri),
            secret_id=secret.id,
            enabled=body.get('enabled', True),
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    if TriggerRepository.query.filter_by(uri=repo.uri).first():
        raise InvalidRequest(f"Trigger repository {repo.uri} already exists", code=HTTPStatus.CONFLICT)
    repo.add()

    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
@auth(scope='can_do_admin')
def patch_repository(repo_id):
    """
    PATCH /global/repositories/triggers/<id> — update repository. Every project it is linked to has
    to be locked and drained, except to rotate the credentials only.
    """
    repo = TriggerRepository.get_by_id(repo_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")
    unknown = set(body) - {'provider', 'api_uri', 'secret_label', 'enabled'}
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")

    # Rotating the credentials only is exempt from the lock, the uri is not changed
    if set(body) != {'secret_label'}:
        require_all_drained([a.project for a in repo.project_assignments])

    if 'secret_label' in body:
        if not body['secret_label']:
            raise InvalidRequest("secret_label cannot be empty")
        repo.secret_id = Secret.get_by_label(body['secret_label']).id

    if 'enabled' in body:
        if not isinstance(body['enabled'], bool):
            raise InvalidRequest("enabled must be a boolean")
        repo.enabled = body['enabled']

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
