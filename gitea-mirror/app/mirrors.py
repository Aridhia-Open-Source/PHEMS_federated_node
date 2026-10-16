from datetime import datetime, timezone
from http import HTTPStatus
import requests
from flask import Blueprint, current_app, request
from sqlalchemy import func, select

from app import sync
from app.clients import UserSyncError
from app.gitea import GiteaError
from app.helpers.base_model import db
from app.helpers.errors import Conflict, NotFound
from app.helpers.validation import validate_mirror
from app.models.mirror import Mirror, MirrorState, MirroredPullRequest
from app.users import sync_users

bp = Blueprint('mirrors', __name__, url_prefix='/mirrors')

MIRROR_FIELDS = (
    'id', 'upstream_uri', 'secret_namespace', 'secret_key',
    'gitea_owner', 'gitea_repo', 'base_branch', 'enabled'
)
# GitHub answers 401 "Bad credentials" for an expired or revoked token. The sync engine (m5)
# records last_error as 'token_expired: ...' when it sees that; either form flags the mirror.
TOKEN_EXPIRED_MARKERS = ('token_expired', 'bad credentials')


def serialize(mirror: Mirror) -> dict:
    return {f: getattr(mirror, f) for f in MIRROR_FIELDS}


def get_mirror(mirror_id: int) -> Mirror:
    mirror = db.session.get(Mirror, mirror_id)
    if mirror is None:
        raise NotFound(f'Mirror {mirror_id} not found')
    return mirror


def check_unique(upstream_uri, gitea_owner, gitea_repo, exclude_id=None):
    query = select(Mirror.id).where(Mirror.upstream_uri == upstream_uri)
    existing = db.session.scalar(query)
    if existing is not None and existing != exclude_id:
        raise Conflict(f'upstream_uri {upstream_uri} already mirrored')
    query = select(Mirror.id).where(
        Mirror.gitea_owner == gitea_owner, Mirror.gitea_repo == gitea_repo
    )
    existing = db.session.scalar(query)
    if existing is not None and existing != exclude_id:
        raise Conflict(f'Gitea repository {gitea_owner}/{gitea_repo} already used')


def run_user_sync(mirror: Mirror) -> dict:
    return sync_users(
        mirror,
        current_app.extensions['github_client'],
        current_app.extensions['gitea_client'],
    )


@bp.get('')
def list_mirrors():
    mirrors = db.session.scalars(select(Mirror).order_by(Mirror.id)).all()
    return [serialize(m) for m in mirrors], HTTPStatus.OK


@bp.post('')
def create_mirror():
    body = validate_mirror(request.get_json(silent=True), partial=False)
    check_unique(body['upstream_uri'], body['gitea_owner'], body['gitea_repo'])
    mirror = Mirror(**{f: body[f] for f in body if f != 'enabled'}, enabled=body.get('enabled', True))
    db.session.add(mirror)
    db.session.flush()
    db.session.add(MirrorState(mirror_id=mirror.id, cursor=datetime.now(timezone.utc)))
    db.session.commit()

    # The mirror stays created if the preload fails; users sync can be retried on its own.
    try:
        users = {'status': 'ok', **run_user_sync(mirror)}
    except NotImplementedError as err:
        users = {'status': 'skipped', 'reason': str(err)}
    except UserSyncError as err:
        users = {'status': 'failed', 'reason': str(err)}
    return {**serialize(mirror), 'users_sync': users}, HTTPStatus.CREATED


@bp.get('/<int:mirror_id>')
def get_one(mirror_id):
    return serialize(get_mirror(mirror_id)), HTTPStatus.OK


@bp.patch('/<int:mirror_id>')
def update_mirror(mirror_id):
    mirror = get_mirror(mirror_id)
    body = validate_mirror(request.get_json(silent=True), partial=True)
    check_unique(
        body.get('upstream_uri', mirror.upstream_uri),
        body.get('gitea_owner', mirror.gitea_owner),
        body.get('gitea_repo', mirror.gitea_repo),
        exclude_id=mirror.id,
    )
    for field, value in body.items():
        setattr(mirror, field, value)
    db.session.commit()
    return serialize(mirror), HTTPStatus.OK


@bp.delete('/<int:mirror_id>')
def delete_mirror(mirror_id):
    mirror = get_mirror(mirror_id)
    db.session.delete(mirror)
    db.session.commit()
    return '', HTTPStatus.NO_CONTENT


@bp.get('/<int:mirror_id>/status')
def status(mirror_id):
    mirror = get_mirror(mirror_id)
    state = db.session.get(MirrorState, mirror.id)
    prs = db.session.scalar(
        select(func.count()).select_from(MirroredPullRequest).where(
            MirroredPullRequest.mirror_id == mirror.id
        )
    )
    last_error = state.last_error
    expired = last_error is not None and any(m in last_error.lower() for m in TOKEN_EXPIRED_MARKERS)
    return {
        'mirror_id': mirror.id,
        'cursor': state.cursor,
        'last_sync_at': state.last_sync_at,
        'last_success_at': state.last_success_at,
        'last_error': last_error,
        'prs_mirrored': prs,
        'token_expired': expired,
    }, HTTPStatus.OK


@bp.post('/<int:mirror_id>/resync')
def resync(mirror_id):
    get_mirror(mirror_id)
    ext = current_app.extensions
    try:
        mirrored = sync.resync(mirror_id, ext['github_client'], ext['gitea_client'], ext['git_cache'])
    except sync.MirrorBusy as err:
        return {'error': str(err)}, HTTPStatus.CONFLICT
    except (UserSyncError, GiteaError, sync.GitError, requests.RequestException) as err:
        # Already recorded on mirror_state (status shows it, incl. token_expired).
        return {'error': str(err)}, HTTPStatus.BAD_GATEWAY
    return {'status': 'ok', 'mirrored': mirrored}, HTTPStatus.OK


@bp.post('/<int:mirror_id>/users/sync')
def users_sync(mirror_id):
    mirror = get_mirror(mirror_id)
    try:
        result = run_user_sync(mirror)
    except NotImplementedError as err:
        return {'error': str(err)}, HTTPStatus.NOT_IMPLEMENTED
    except UserSyncError as err:
        return {'error': str(err)}, HTTPStatus.BAD_GATEWAY
    return result, HTTPStatus.OK
