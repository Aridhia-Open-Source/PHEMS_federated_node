import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import select

from app.github import read_secret_token
from app.models.mirror import Mirror, MirroredPullRequest, Webhook, WebhookDelivery

EVENT_PULL_REQUEST_MIRRORED = 'pull_request.mirrored'
EVENT_PING = 'ping'
SIGNATURE_HEADER = 'X-Gitea-Mirror-Signature'
DELIVERY_HEADER = 'X-Gitea-Mirror-Delivery'
EVENT_HEADER = 'X-Gitea-Mirror-Event'
TIMEOUT = 10
MAX_ATTEMPTS = 5
BACKOFF_BASE = timedelta(seconds=30)  # doubles per attempt: 30s, 60s, 120s, 240s
BATCH_SIZE = 50
PENDING, DELIVERED, FAILED = 'pending', 'delivered', 'failed'


def read_hmac_key(namespace: str, key: str) -> str:
    """Tests replace this. Same secret layout as the GitHub token (field `token`)."""
    return read_secret_token(namespace, key)


def sign(body: bytes, key: str) -> str:
    return 'sha256=' + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def build_event(delivery_id: str, mirror: Mirror, pr: MirroredPullRequest) -> dict:
    return {
        'event': EVENT_PULL_REQUEST_MIRRORED,
        'delivery_id': delivery_id,
        'mirror': {
            'upstream_uri': mirror.upstream_uri,
            'gitea_owner': mirror.gitea_owner,
            'gitea_repo': mirror.gitea_repo,
        },
        'number': pr.number,
        'gitea_pr_number': pr.gitea_pr_number,
        'title': pr.title,
        'author': pr.author,
        'merged_at': pr.merged_at.isoformat(),
        'merge_commit_sha': pr.merge_commit_sha,
    }


def post_event(webhook: Webhook, event: dict) -> None:
    """Sign and POST. Raises requests.RequestException on any failure, including non-2xx."""
    key = read_hmac_key(webhook.secret_namespace, webhook.secret_key)
    body = json.dumps(event, separators=(',', ':')).encode()
    response = requests.post(
        webhook.url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            SIGNATURE_HEADER: sign(body, key),
            DELIVERY_HEADER: event['delivery_id'],
            EVENT_HEADER: event['event'],
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def send_ping(webhook: Webhook) -> None:
    post_event(webhook, {'event': EVENT_PING, 'delivery_id': str(uuid.uuid4())})


def enqueue_deliveries(session, pr: MirroredPullRequest) -> list[WebhookDelivery]:
    """
    One pending delivery per enabled webhook for the PR's mirror (or for all mirrors).
    Called by the sync engine inside its transaction; the caller commits.
    """
    if pr.id is None:
        session.flush()
    webhooks = session.scalars(
        select(Webhook).where(
            Webhook.enabled.is_(True),
            (Webhook.mirror_id.is_(None)) | (Webhook.mirror_id == pr.mirror_id),
        ).order_by(Webhook.id)
    ).all()
    now = datetime.now(timezone.utc)
    deliveries = [
        WebhookDelivery(
            webhook_id=w.id, mirrored_pull_request_id=pr.id, status=PENDING,
            attempts=0, next_attempt_at=now,
        )
        for w in webhooks
    ]
    session.add_all(deliveries)
    session.flush()
    return deliveries


def process_due_deliveries(session, now: datetime | None = None) -> int:
    """Attempt every pending delivery that is due, once. Commits per delivery. Returns the count."""
    now = now or datetime.now(timezone.utc)
    due = session.scalars(
        select(WebhookDelivery).where(
            WebhookDelivery.status == PENDING, WebhookDelivery.next_attempt_at <= now
        ).order_by(WebhookDelivery.id).limit(BATCH_SIZE).with_for_update(skip_locked=True)
    ).all()
    for delivery in due:
        attempt_delivery(session, delivery, now)
        session.commit()
    return len(due)


def attempt_delivery(session, delivery: WebhookDelivery, now: datetime) -> None:
    webhook = session.get(Webhook, delivery.webhook_id)
    pr = session.get(MirroredPullRequest, delivery.mirrored_pull_request_id)
    mirror = session.get(Mirror, pr.mirror_id)
    delivery.attempts += 1
    try:
        post_event(webhook, build_event(str(delivery.id), mirror, pr))
    except requests.RequestException as err:
        delivery.last_error = str(err)[:4096]
        if delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = FAILED
            delivery.next_attempt_at = None
        else:
            delivery.next_attempt_at = now + BACKOFF_BASE * 2 ** (delivery.attempts - 1)
    else:
        delivery.status = DELIVERED
        delivery.next_attempt_at = None
        delivery.last_error = None
