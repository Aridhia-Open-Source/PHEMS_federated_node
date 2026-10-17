"""
Git provider endpoints, global: the trigger and results repositories refer to one by id. All
admin only. Changing anything but the name changes every repository on the provider, so it
needs every project linked to one of them locked and drained.
- GET /global/providers
- GET /global/providers/<id>
- POST /global/providers
- PATCH /global/providers/<id>
- DELETE /global/providers/<id>
- GET /global/providers/<id>/healthcheck, see healthcheck_api.py
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.git_provider import GitProviderDTO, GitProviderPatchRequest, GitProviderRequest
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.helpers.project_lock import require_all_drained
from app.helpers.wrappers import auth
from app.models.git_provider import GitProvider

bp = Blueprint('git_providers', __name__, url_prefix='/global/providers')
session = db.session


@bp.before_request
@auth(scope='can_admin_dataset')
def auth_before():
    """Ensure the user is authenticated."""


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


@bp.route('/', methods=['GET'])
@bp.route('', methods=['GET'])
def get_providers():
    """
    GET /global/providers/ — list the providers
    """
    return [GitProviderDTO.from_model(p).dump() for p in GitProvider.query.order_by(GitProvider.id)], HTTPStatus.OK


@bp.route('/<int:provider_id>', methods=['GET'])
def get_provider(provider_id):
    """
    GET /global/providers/<id> — get a single provider
    """
    return GitProviderDTO.from_model(GitProvider.get_by_id(provider_id)).dump(), HTTPStatus.OK


@bp.route('/', methods=['POST'])
@bp.route('', methods=['POST'])
@auth(scope='can_do_admin')
def post_provider():
    """
    POST /global/providers/ — create a provider. The name and the uri are unique (409).
    Body: {"name": "...", "type": "github", "uri": "https://github.com", "api_uri": "https://api.github.com",
    "enabled": true}. enabled is optional.
    """
    req = GitProviderRequest.parse(request.json or {})
    try:
        provider = GitProvider(name=req.name, type=req.type, uri=req.uri, api_uri=req.api_uri, enabled=req.enabled)
    except ValueError as e:
        raise InvalidRequest(str(e))
    _check_unique(provider)
    provider.add()

    return GitProviderDTO.from_model(provider).dump(), HTTPStatus.CREATED


@bp.route('/<int:provider_id>', methods=['PATCH'])
@auth(scope='can_do_admin')
def patch_provider(provider_id):
    """
    PATCH /global/providers/<id> — update a provider. Anything but the name
    needs every project linked to a repository on it locked and drained.
    """
    provider = GitProvider.get_by_id(provider_id)

    body = request.json or {}
    if not body:
        raise InvalidRequest("No fields provided to update")
    req = GitProviderPatchRequest.parse(body)

    if set(body) - {'name'}:
        links = [
            *(a for r in provider.trigger_repositories for a in r.project_assignments),
            *(a for r in provider.results_repositories for a in r.project_assignments),
        ]
        require_all_drained([a.project for a in links])

    try:
        for field in ('name', 'type', 'enabled'):
            if field in body:
                setattr(provider, field, getattr(req, field))
        # uri before api_uri, which has to be on the uri's host
        if 'uri' in body:
            provider.uri = req.uri
        if 'api_uri' in body or 'uri' in body:
            provider.api_uri = req.api_uri or provider.api_uri
    except ValueError as e:
        raise InvalidRequest(str(e))
    _check_unique(provider, provider.id)

    session.commit()
    return GitProviderDTO.from_model(provider).dump(), HTTPStatus.OK


@bp.route('/<int:provider_id>', methods=['DELETE'])
@auth(scope='can_do_admin')
def delete_provider(provider_id):
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
    provider.delete()
    return '', HTTPStatus.NO_CONTENT
