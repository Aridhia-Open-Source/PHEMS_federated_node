"""
trigger repository endpoints, global: a project is linked to one under
/projects/<id>/repositories/triggers (see project_trigger_repositories_api.py). Create, edit and delete are admin
only. Deleting, or turning one on or off (enabled), needs every project the repository is linked to locked and
drained; any other edit applies at once. A secret_label naming a disabled secret is a 400 on POST and PATCH.
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

from flask import Blueprint, request

from app.dtos.base import page_of
from app.dtos.repository_uri import RepositoryPatchRequest, RepositoryRequest
from app.dtos.trigger_repository import PullRequestDTO, PullRequestRequest, TriggerRepositoryDTO
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.query_filters import arg_get
from app.helpers.project_lock import require_all_drained, require_all_drained_if_enabled
from app.helpers.pull_request_fanout import ingest_pull_requests, skip_gap
from app.helpers.wrappers import auth
from app.models.git_provider import GitProvider
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
    GET /global/repositories/triggers/ — list the repositories. With ?pollable=true only the enabled
    repositories on an enabled provider with an enabled secret, whatever their project links: that is
    what Dagster polls.
    """
    query = TriggerRepository.query
    if request.args.get('pollable', '').lower() == 'true':
        query = query.filter(
            TriggerRepository.enabled.is_(True),
            TriggerRepository.provider.has(GitProvider.enabled.is_(True)),
            TriggerRepository.secret.has(Secret.enabled.is_(True)),
        )
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
    Query params: page (default 1), per_page (default 20), both clamped to at least 1.
    Responds with page, per_page, total, pages and items.
    """
    TriggerRepository.get_by_id(repo_id)
    page = max(arg_get('page', 1, type=int), 1)
    per_page = max(arg_get('per_page', 20, type=int), 1)
    paginated = PullRequest.query.filter_by(trigger_repository_id=repo_id)\
        .order_by(PullRequest.merged_at.desc(), PullRequest.number.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    return page_of(paginated, PullRequestDTO), HTTPStatus.OK


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
    if not repo.active:
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
    req = RepositoryRequest.parse(body)

    provider = GitProvider.get_by_request_id(req.provider_id)
    secret = Secret.get_enabled_by_label(req.secret_label)

    try:
        repo = TriggerRepository(
            provider_id=provider.id,
            repo_path=req.repo_path,
            secret_id=secret.id,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise InvalidRequest(str(e))
    if TriggerRepository.query.filter_by(provider_id=provider.id, repo_path=repo.repo_path).first():
        raise InvalidRequest(
            f"Trigger repository {provider.uri}/{repo.repo_path} already exists", code=HTTPStatus.CONFLICT
        )
    repo.add()

    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.CREATED


@bp.route('/<int:repo_id>', methods=['PATCH'])
@auth(scope='can_do_admin')
def patch_repository(repo_id):
    """
    PATCH /global/repositories/triggers/<id> — update repository. Only a change of enabled needs every
    project it is linked to locked and drained, any other edit applies at once (the tasks created
    before are pinned to the old setup and fail instead of running against the new one). A disabled secret cannot be
    named (400), unless it is the one already in use.
    """
    repo = TriggerRepository.get_by_id(repo_id)

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
        # Switched back on: what was merged while it was off gets no trigger
        if req.enabled and not repo.enabled:
            skip_gap(repo.project_assignments)
        repo.enabled = req.enabled

    if 'provider_id' in body:
        provider = GitProvider.get_by_request_id(req.provider_id)
        if TriggerRepository.query.filter(
            TriggerRepository.provider_id == provider.id, TriggerRepository.repo_path == repo.repo_path, TriggerRepository.id != repo.id
        ).first():
            raise InvalidRequest(
                f"Trigger repository {provider.uri}/{repo.repo_path} already exists", code=HTTPStatus.CONFLICT
            )
        repo.provider_id = provider.id

    session.commit()
    return TriggerRepositoryDTO.from_model(repo).dump(), HTTPStatus.OK
