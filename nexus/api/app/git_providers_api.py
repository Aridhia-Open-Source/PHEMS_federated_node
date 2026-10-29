"""
Git provider endpoints, global: the trigger and results repositories refer to one by id. All
admin only. Deleting is a soft delete.
- GET /global/providers
- GET /global/providers/<id>
- POST /global/providers
- PATCH /global/providers/<id>
- DELETE /global/providers/<id>
- GET /global/providers/<id>/healthcheck, see healthcheck_api.py
"""
from http import HTTPStatus

from fastapi import APIRouter, Depends

from app.dtos.git_provider import GitProviderDTO, GitProviderPatchRequest, GitProviderRequest
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest, UnauthorizedError
from app.helpers.pull_request_fanout import skip_gap
from app.helpers.wrappers import Caller, get_caller, require_scope
from app.models.git_provider import GitProvider

router = APIRouter(
    prefix='/global/providers', tags=["git_providers"], dependencies=[Depends(require_scope('can_admin_dataset'))]
)
session = db.session


def _check_unique(provider: GitProvider, current_id: int | None = None):
    """The name and the uri are each unique across the node, a 409 if another provider has one."""
    for field in ('name', 'uri'):
        # The provider may be changed and not stored yet: a flush now would fail on the duplicate
        with session.no_autoflush:
            taken = GitProvider.query.filter(
                getattr(GitProvider, field) == getattr(provider, field), GitProvider.id != current_id
            ).first()
        if taken:
            raise InvalidRequest(
                f"Git provider with {field} {getattr(provider, field)} already exists", code=HTTPStatus.CONFLICT
            )


@router.get('/', response_model=list[GitProviderDTO])
@router.get('', response_model=list[GitProviderDTO])
def get_providers():
    """
    GET /global/providers/ — list the providers
    """
    return [GitProviderDTO.from_model(p) for p in GitProvider.query.order_by(GitProvider.id)]


@router.get('/{provider_id}', response_model=GitProviderDTO)
def get_provider(provider_id: int):
    """
    GET /global/providers/<id> — get a single provider
    """
    return GitProviderDTO.from_model(GitProvider.get_by_id(provider_id))


@router.post('/', status_code=HTTPStatus.CREATED, response_model=GitProviderDTO,
             dependencies=[Depends(require_scope('can_do_admin'))])
@router.post('', status_code=HTTPStatus.CREATED, response_model=GitProviderDTO,
             dependencies=[Depends(require_scope('can_do_admin'))])
def post_provider(req: GitProviderRequest):
    """
    POST /global/providers/ — create a provider. The name and the uri are unique (409).
    Body: {"name": "...", "type": "github", "uri": "https://github.com", "api_uri": "https://api.github.com",
    "enabled": true}. enabled is optional.
    """
    try:
        provider = GitProvider(name=req.name, type=req.type, uri=req.uri, api_uri=req.api_uri, enabled=req.enabled)
    except ValueError as e:
        raise InvalidRequest(str(e))
    _check_unique(provider)
    provider.add()

    return GitProviderDTO.from_model(provider)


@router.patch('/{provider_id}', response_model=GitProviderDTO, dependencies=[Depends(require_scope('can_do_admin'))])
def patch_provider(provider_id: int, req: GitProviderPatchRequest, caller: Caller = Depends(get_caller)):
    """
    PATCH /global/providers/<id> — update a provider. The tasks created before
    are pinned to the old setup and fail instead of running against the new one. `revoked` (a boolean) withdraws
    the provider, and so every repository on it, from every project at once, or restores it, and does not
    change `enabled`: see helpers/task_config.revoked_resources.
    """
    provider = GitProvider.get_by_id(provider_id)

    sent = req.model_fields_set
    if not sent:
        raise InvalidRequest("No fields provided to update")
    if 'revoked' in sent and not caller.is_admin:
        raise UnauthorizedError("Only an admin can revoke or re-grant a git provider")

    was_enabled, was_revoked = provider.enabled, provider.revoked
    try:
        for field in ('name', 'type', 'enabled', 'revoked'):
            if field in sent:
                setattr(provider, field, getattr(req, field))
        # uri before api_uri, which has to be on the uri's host
        if 'uri' in sent:
            provider.uri = req.uri
        if 'api_uri' in sent or 'uri' in sent:
            provider.api_uri = req.api_uri or provider.api_uri
    except ValueError as e:
        raise InvalidRequest(str(e))
    _check_unique(provider, provider.id)

    # Switched back on or restored: what was merged while it was off or revoked gets no trigger
    if (provider.enabled and not was_enabled) or (was_revoked and not provider.revoked):
        skip_gap([a for r in provider.trigger_repositories for a in r.project_assignments])

    session.commit()
    return GitProviderDTO.from_model(provider)


@router.delete('/{provider_id}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(require_scope('can_do_admin'))])
def delete_provider(provider_id: int):
    """
    DELETE /global/providers/<id> — delete the provider. Refused with a 409 while a repository
    is on it.
    """
    provider = GitProvider.get_by_id(provider_id)
    users = len(provider.trigger_repositories) + len(provider.results_repositories)
    if users:
        raise InvalidRequest(
            f"Git provider {provider.name} is still used by {users} repositories", code=HTTPStatus.CONFLICT
        )
    provider.soft_delete()
    session.commit()
