"""
trigger repository endpoints, global: a project is linked to one under
/projects/<id>/repositories/triggers (see project_trigger_repositories_api.py). Create, edit and delete are admin
only. Deleting one is a soft delete, refused with a 409 naming the projects it is linked to unless ?force=true. A secret_label naming a disabled secret is a 400 on POST and PATCH.
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

from fastapi import APIRouter, Body, Depends

from app.dtos.base import page_of
from app.dtos.repository_uri import RepositoryPatchRequest, RepositoryRequest
from app.dtos.trigger_repository import PullRequestDTO, PullRequestRequest, TriggerRepositoryDTO
from app.helpers.base_model import db, paginate
from app.helpers.exceptions import InvalidRequest, UnauthorizedError
from app.helpers.query_filters import QueryFilters, arg_get
from app.helpers.pull_request_fanout import ingest_pull_requests, skip_gap
from app.helpers.soft_delete import delete_global
from app.helpers.wrappers import Caller, get_caller, require_scope, system_only
from app.models.git_provider import GitProvider
from app.models.pull_request import PullRequest
from app.models.trigger_repository import TriggerRepository
from app.models.secret import Secret

router = APIRouter(
    prefix='/global/repositories/triggers', tags=["trigger_repositories"],
    dependencies=[Depends(require_scope('can_admin_dataset'))]
)
session = db.session


@router.get('/', response_model=list[TriggerRepositoryDTO])
@router.get('', response_model=list[TriggerRepositoryDTO])
def get_repositories(pollable: str = ''):
    """
    GET /global/repositories/triggers/ — list the repositories. With ?pollable=true only the enabled and
    not revoked repositories on an enabled, not revoked provider with an enabled secret, whatever their project
    links: that is what Dagster polls.
    """
    query = TriggerRepository.query
    if pollable.lower() == 'true':
        query = query.filter(
            TriggerRepository.enabled.is_(True),
            TriggerRepository.revoked.is_(False),
            TriggerRepository.provider.has(GitProvider.enabled.is_(True) & GitProvider.revoked.is_(False)),
            TriggerRepository.secret.has(Secret.enabled.is_(True)),
        )
    return [TriggerRepositoryDTO.from_model(r) for r in query.order_by(TriggerRepository.id)]


@router.get('/{repo_id}', response_model=TriggerRepositoryDTO)
def get_repository(repo_id: int):
    """
    GET /global/repositories/triggers/<id> — get a single repository
    """
    repo = TriggerRepository.get_by_id(repo_id)
    return TriggerRepositoryDTO.from_model(repo)


@router.get('/{repo_id}/pull_requests')
def get_pull_requests(repo_id: int, filters: QueryFilters = Depends()):
    """
    GET /global/repositories/triggers/<id>/pull_requests — the provider's facts of the pull requests
    stored for the repository, most recent merge first.
    Query params: page (default 1), per_page (default 20), both clamped to at least 1.
    Responds with page, per_page, total, pages and items.
    """
    TriggerRepository.get_by_id(repo_id)
    page = max(arg_get(filters, 'page', 1, type=int), 1)
    per_page = max(arg_get(filters, 'per_page', 20, type=int), 1)
    query = PullRequest.query.filter_by(trigger_repository_id=repo_id)\
        .order_by(PullRequest.merged_at.desc(), PullRequest.number.desc())
    return page_of(paginate(query, page, per_page), PullRequestDTO)


@router.post('/{repo_id}/pull_requests', status_code=HTTPStatus.CREATED, dependencies=[Depends(system_only)])
def post_pull_requests_batch(repo_id: int, body: dict = Body(default_factory=dict)):
    """
    POST /global/repositories/triggers/<id>/pull_requests — store up to 100 pull requests of the
    repository and create their triggers for every active assignment. Idempotent: a number
    already stored is left as it is. Refused for a disabled or revoked repository (or one on such a provider), which stores nothing.
    Responds with the numbers stored and those already there.
    Body: {"pull_requests": [pull requests, see PullRequestRequest]}
    """
    repo = TriggerRepository.get_by_id(repo_id)
    if not repo.active:
        raise InvalidRequest(f"Trigger repository {repo.uri} is disabled or revoked")
    pull_requests = body.get('pull_requests')
    if not isinstance(pull_requests, list):
        raise InvalidRequest("pull_requests must be a list of pull requests")
    # The cap is fine; the Dagster ingest sensor must chunk its posts.
    # One invalid PR (PullRequestRequest.parse) also refuses the whole batch.
    if len(pull_requests) > 100:
        raise InvalidRequest("Maximum 100 pull requests per batch")

    created, existing = ingest_pull_requests(repo.id, [PullRequestRequest.parse(pr) for pr in pull_requests])
    session.commit()
    return {
        'created': [pr.number for pr in created],
        'existing': [pr.number for pr in existing],
    }


@router.delete('/{repo_id}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(require_scope('can_do_admin'))])
def delete_repository(repo_id: int, force: bool = False):
    """
    DELETE /global/repositories/triggers/<id> — soft delete the repository. A 409 names the projects it is linked to, unless ?force=true, which also revokes and deletes their links.
    """
    repo = TriggerRepository.get_by_id(repo_id)
    delete_global(repo, repo.project_assignments, force)


@router.post('/', status_code=HTTPStatus.CREATED, response_model=TriggerRepositoryDTO,
             dependencies=[Depends(require_scope('can_do_admin'))])
@router.post('', status_code=HTTPStatus.CREATED, response_model=TriggerRepositoryDTO,
             dependencies=[Depends(require_scope('can_do_admin'))])
def post_repository(body: dict = Body(default_factory=dict)):
    """
    POST /global/repositories/triggers/ — create a new repository, linked to no project yet.
    """
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

    return TriggerRepositoryDTO.from_model(repo)


@router.patch('/{repo_id}', response_model=TriggerRepositoryDTO,
              dependencies=[Depends(require_scope('can_do_admin'))])
def patch_repository(repo_id: int, body: dict = Body(default_factory=dict), caller: Caller = Depends(get_caller)):
    """
    PATCH /global/repositories/triggers/<id> — update repository. The tasks created
    before are pinned to the old setup and fail instead of running against the new one. A disabled secret cannot be
    named (400), unless it is the one already in use. Enabling the repository is a 409 while its secret (the new one,
    if secret_label is also sent) is disabled or deleted. `revoked` (a boolean) withdraws the repository from every
    project at once, or restores it, and does not change `enabled`: see helpers/task_config.revoked_resources.
    """
    repo = TriggerRepository.get_by_id(repo_id)

    if not body:
        raise InvalidRequest("No fields provided to update")
    unknown = set(body) - {'provider_id', 'secret_label', 'enabled', 'revoked'}
    if unknown:
        raise InvalidRequest(f"Fields cannot be updated: {', '.join(sorted(unknown))}")
    req = RepositoryPatchRequest.parse(body)
    if 'revoked' in body and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a trigger repository")

    secret = repo.secret
    if 'secret_label' in body:
        secret = Secret.get_enabled_by_label(req.secret_label, repo.secret_id)
    if 'enabled' in body and req.enabled:
        secret.require_usable()
    repo.secret_id = secret.id

    if 'enabled' in body:
        # Switched back on: what was merged while it was off gets no trigger
        if req.enabled and not repo.enabled:
            skip_gap(repo.project_assignments)
        repo.enabled = req.enabled

    if 'revoked' in body:
        # Restored: what was merged while it was revoked gets no trigger
        if repo.revoked and not req.revoked:
            skip_gap(repo.project_assignments)
        repo.revoked = req.revoked

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
    return TriggerRepositoryDTO.from_model(repo)
