from http import HTTPStatus
from urllib.parse import urlparse

import requests
from flask import Blueprint, request
from sqlalchemy import select

from app import delivery
from app.helpers.base_model import db
from app.helpers.errors import BadRequest, NotFound
from app.models.mirror import Mirror, Webhook, WebhookDelivery

bp = Blueprint('webhooks', __name__, url_prefix='/webhooks')

WEBHOOK_FIELDS = ('id', 'url', 'secret_namespace', 'secret_key', 'mirror_id', 'enabled')
STRING_FIELDS = ('url', 'secret_namespace', 'secret_key')
REQUIRED_FIELDS = STRING_FIELDS
MAX_LEN = 256
MAX_URL_LEN = 512
DELIVERIES_LIMIT = 100


def validate_webhook(body, partial: bool) -> dict:
    if not isinstance(body, dict):
        raise BadRequest('Body must be a JSON object')
    unknown = set(body) - set(STRING_FIELDS) - {'enabled', 'mirror_id'}
    if unknown:
        raise BadRequest(f'Unknown fields: {", ".join(sorted(unknown))}')
    if not partial:
        missing = [f for f in REQUIRED_FIELDS if f not in body]
        if missing:
            raise BadRequest(f'Missing required fields: {", ".join(missing)}')
    for field in STRING_FIELDS:
        if field in body:
            value = body[field]
            max_len = MAX_URL_LEN if field == 'url' else MAX_LEN
            if not isinstance(value, str) or not value.strip() or len(value) > max_len:
                raise BadRequest(f'{field} must be a non-empty string of at most {max_len} chars')
    if 'enabled' in body and not isinstance(body['enabled'], bool):
        raise BadRequest('enabled must be a boolean')
    if 'mirror_id' in body:
        mirror_id = body['mirror_id']
        if mirror_id is not None and (isinstance(mirror_id, bool) or not isinstance(mirror_id, int)):
            raise BadRequest('mirror_id must be an integer or null')
        if mirror_id is not None and db.session.get(Mirror, mirror_id) is None:
            raise BadRequest(f'mirror_id {mirror_id} does not exist')
    if 'url' in body:
        parsed = urlparse(body['url'])
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise BadRequest('url must be an http or https URL')
    return body


def serialize(webhook: Webhook) -> dict:
    return {f: getattr(webhook, f) for f in WEBHOOK_FIELDS}


def serialize_delivery(row: WebhookDelivery) -> dict:
    return {
        'id': row.id,
        'webhook_id': row.webhook_id,
        'mirrored_pull_request_id': row.mirrored_pull_request_id,
        'status': row.status,
        'attempts': row.attempts,
        'next_attempt_at': row.next_attempt_at,
        'last_error': row.last_error,
    }


def get_webhook(webhook_id: int) -> Webhook:
    webhook = db.session.get(Webhook, webhook_id)
    if webhook is None:
        raise NotFound(f'Webhook {webhook_id} not found')
    return webhook


@bp.get('')
def list_webhooks():
    webhooks = db.session.scalars(select(Webhook).order_by(Webhook.id)).all()
    return [serialize(w) for w in webhooks], HTTPStatus.OK


@bp.post('')
def create_webhook():
    body = validate_webhook(request.get_json(silent=True), partial=False)
    webhook = Webhook(**body)
    if 'enabled' not in body:
        webhook.enabled = True
    db.session.add(webhook)
    db.session.commit()
    return serialize(webhook), HTTPStatus.CREATED


@bp.get('/<int:webhook_id>')
def get_one(webhook_id):
    return serialize(get_webhook(webhook_id)), HTTPStatus.OK


@bp.patch('/<int:webhook_id>')
def update_webhook(webhook_id):
    webhook = get_webhook(webhook_id)
    body = validate_webhook(request.get_json(silent=True), partial=True)
    for field, value in body.items():
        setattr(webhook, field, value)
    db.session.commit()
    return serialize(webhook), HTTPStatus.OK


@bp.delete('/<int:webhook_id>')
def delete_webhook(webhook_id):
    db.session.delete(get_webhook(webhook_id))
    db.session.commit()
    return '', HTTPStatus.NO_CONTENT


@bp.post('/<int:webhook_id>/test')
def test_webhook(webhook_id):
    webhook = get_webhook(webhook_id)
    try:
        delivery.send_ping(webhook)
    except requests.RequestException as err:
        return {'status': 'failed', 'error': str(err)}, HTTPStatus.BAD_GATEWAY
    return {'status': 'ok'}, HTTPStatus.OK


@bp.get('/<int:webhook_id>/deliveries')
def deliveries(webhook_id):
    get_webhook(webhook_id)
    query = select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook_id)
    status = request.args.get('status')
    if status is not None:
        query = query.where(WebhookDelivery.status == status)
    rows = db.session.scalars(query.order_by(WebhookDelivery.id.desc()).limit(DELIVERIES_LIMIT)).all()
    return [serialize_delivery(r) for r in rows], HTTPStatus.OK
