import ipaddress
import json
import os
import re
import socket
import uuid
from http import HTTPStatus
from urllib.parse import urlparse

import requests
from flask import Blueprint, request
from sqlalchemy import select

from app import delivery
from app.helpers.base_model import db
from app.helpers.validation import validate_secret_ref
from app.helpers.errors import BadRequest, NotFound
from app.models.mirror import Mirror, Webhook, WebhookDelivery

bp = Blueprint('webhooks', __name__, url_prefix='/webhooks')

WEBHOOK_FIELDS = ('id', 'url', 'secret_namespace', 'secret_key', 'mirror_id', 'enabled')
STRING_FIELDS = ('url', 'secret_namespace', 'secret_key')
REQUIRED_FIELDS = STRING_FIELDS
MAX_LEN = 256
MAX_URL_LEN = 512
DELIVERIES_LIMIT = 100


ALLOW_PRIVATE_ENV = 'GITEA_MIRROR_WEBHOOK_ALLOW_PRIVATE'
CONTROL_OR_SPACE = re.compile(r'[\x00-\x20\x7f]')
API_SERVER_HOSTS = ('kubernetes.default', 'kubernetes.default.svc', 'kubernetes.default.svc.cluster.local')


class UrlRejected(Exception):
    """A webhook URL breaks the target policy."""


def allow_private() -> bool:
    return os.environ.get(ALLOW_PRIVATE_ENV, 'true').strip().lower() not in ('false', '0', 'no', 'off')


def resolve_host(host: str) -> list[str]:
    """Every address the host resolves to. Tests replace this."""
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})


def check_address(address: str) -> None:
    ip = ipaddress.ip_address(address.split('%')[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise UrlRejected('url must not target a loopback, link-local, metadata or unspecified address')
    if str(ip) == os.environ.get('KUBERNETES_SERVICE_HOST'):
        raise UrlRejected('url must not target the Kubernetes API server')
    if not allow_private() and not ip.is_global:
        raise UrlRejected('url must not target a private address')


def check_webhook_url(url: str) -> None:
    """
    Policy: http/https, no userinfo, host resolves, and every resolved address passes
    check_address. In-cluster receivers (*.svc.cluster.local, private ranges) are allowed by
    default; loopback, link-local (incl. 169.254.169.254), unspecified and the API server never.
    """
    if CONTROL_OR_SPACE.search(url):
        raise UrlRejected('url must not contain whitespace or control characters')
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise UrlRejected('url must be an http or https URL')
    try:
        parsed.port
    except ValueError:
        raise UrlRejected('url has an invalid port')
    if parsed.username is not None or parsed.password is not None or '@' in parsed.netloc:
        raise UrlRejected('url must not contain credentials')
    host = parsed.hostname
    if not host:
        raise UrlRejected('url has no host')
    host = host.rstrip('.').lower()
    if host in API_SERVER_HOSTS:
        raise UrlRejected('url must not target the Kubernetes API server')
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = resolve_host(host)
        except OSError:
            raise UrlRejected('url host does not resolve')
    if not addresses:
        raise UrlRejected('url host does not resolve')
    for address in addresses:
        check_address(address)


def check_secret_exists(namespace: str, key: str) -> None:
    """Same reader the delivery uses; the secret must exist and carry a non-empty key."""
    try:
        value = delivery.read_hmac_key(namespace, key)
    except Exception:
        raise BadRequest('secret_namespace/secret_key does not name a readable secret with a token field')
    if not value:
        raise BadRequest('secret_namespace/secret_key names an empty secret')


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
    validate_secret_ref(body)
    if 'url' in body:
        try:
            check_webhook_url(body['url'])
        except UrlRejected as err:
            raise BadRequest(str(err))
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
    check_secret_exists(body['secret_namespace'], body['secret_key'])
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
    if 'secret_namespace' in body or 'secret_key' in body:
        check_secret_exists(
            body.get('secret_namespace', webhook.secret_namespace),
            body.get('secret_key', webhook.secret_key),
        )
    for field, value in body.items():
        setattr(webhook, field, value)
    db.session.commit()
    return serialize(webhook), HTTPStatus.OK


@bp.delete('/<int:webhook_id>')
def delete_webhook(webhook_id):
    db.session.delete(get_webhook(webhook_id))
    db.session.commit()
    return '', HTTPStatus.NO_CONTENT


def send_ping(webhook: Webhook) -> None:
    """Signed ping. Re-checks the stored URL and never follows redirects."""
    check_webhook_url(webhook.url)
    key = delivery.read_hmac_key(webhook.secret_namespace, webhook.secret_key)
    event = {'event': delivery.EVENT_PING, 'delivery_id': str(uuid.uuid4())}
    body = json.dumps(event, separators=(',', ':')).encode()
    response = requests.post(
        webhook.url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            delivery.SIGNATURE_HEADER: delivery.sign(body, key),
            delivery.DELIVERY_HEADER: event['delivery_id'],
            delivery.EVENT_HEADER: event['event'],
        },
        timeout=delivery.TIMEOUT,
        allow_redirects=False,
    )
    response.raise_for_status()
    if not response.ok or not 200 <= response.status_code < 300:  # an unfollowed 3xx is a failure too
        raise requests.HTTPError(f'unexpected status {response.status_code}')


@bp.post('/<int:webhook_id>/test')
def test_webhook(webhook_id):
    webhook = get_webhook(webhook_id)
    try:
        send_ping(webhook)
    except Exception as err:
        # Only the exception class: the message would be a port/host scan oracle.
        return {'status': 'failed', 'reason': type(err).__name__}, HTTPStatus.BAD_GATEWAY
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
