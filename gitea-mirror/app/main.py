from http import HTTPStatus
from flask import Blueprint
from sqlalchemy import text
from app.helpers.base_model import db

bp = Blueprint('main', __name__, url_prefix='/')


@bp.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return {'status': 'ok'}, HTTPStatus.OK
    except Exception:
        return {'status': 'error'}, HTTPStatus.INTERNAL_SERVER_ERROR
