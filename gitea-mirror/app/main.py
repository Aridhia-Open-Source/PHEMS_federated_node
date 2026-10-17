from http import HTTPStatus
from flask import Blueprint, current_app
from sqlalchemy import text
from app.helpers.base_model import db

bp = Blueprint('main', __name__, url_prefix='/')


@bp.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        return {'status': 'error'}, HTTPStatus.INTERNAL_SERVER_ERROR
    # Registered by the container runner only; absent under tests and the bare API.
    sync = current_app.extensions.get('sync_status')
    if sync is None:
        return {'status': 'ok'}, HTTPStatus.OK
    snapshot = sync.snapshot()
    healthy = snapshot.pop('healthy')
    body = {'status': 'ok' if healthy else 'error', 'sync': snapshot}
    return body, HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE
