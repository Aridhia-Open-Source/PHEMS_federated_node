import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import select, update

from app.github import read_secret_token
from app.models.mirror import Mirror, MirroredPullRequest, Webhook, WebhookDelivery

EVENT_PULL_REQUEST_MIRRORED = 'pull_request.mirrored'
EVENT_PING = 'ping'
SIGNATURE_HEADER = 'X-Gitea-Mirror-Signature'
DELIVERY_HEADER = 'X-Gitea-Mirror-Delivery'
EVENT_HEADER = 'X-Gitea-Mirror-Event'
# Unix seconds at send time. NOT covered by the signature: the documented contract is the HMAC
# over the raw body only, and signing `<timestamp>.<body>` would break existing receivers.
# Replay gap: an attacker who captures a request can resend it with a fresh timestamp header, so
# receivers must still dedupe on X-Gitea-Mirror-Delivery (a UUID, stable across DB resets).
TIMESTAMP_HEADER = 'X-Gitea-Mirror-Timestamp'
TIMEOUT = 10
MAX_ATTEMPTS = 5
BACKOFF_BASE = timedelta(seconds=30)  # doubles per attempt: 30s, 60s, 120s, 240s
BATCH_SIZE = 50
# A claimed row is invisible to other runners for this long (every POST in a full batch could
# take TIMEOUT). A runner that dies mid-batch has its rows retried after the lease expires.
LEASE = timedelta(seconds=BATCH_SIZE * TIMEOUT + 60)
logger = logging.getLogger(__name__)
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
            TIMESTAMP_HEADER: str(int(time.time())),
        },
        timeout=TIMEOUT,
        allow_redirects=False,  # an internal receiver must not bounce us to another host
    )
    if not 200 <= response.status_code < 300:  # includes 3xx, which raise_for_status accepts
        raise requests.HTTPError(str(response.status_code), response=response)


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


def claim_due_deliveries(session, now: datetime) -> list[int]:
    """
    Lease up to BATCH_SIZE due deliveries and commit the lease, returning their ids.
    SKIP LOCKED only protects until the first commit, so the claim itself is the lock:
    next_attempt_at moves LEASE into the future before anything is POSTed.
    """
    due = session.scalars(
        select(WebhookDelivery).where(
            WebhookDelivery.status == PENDING, WebhookDelivery.next_attempt_at <= now
        ).order_by(WebhookDelivery.id).limit(BATCH_SIZE).with_for_update(skip_locked=True)
    ).all()
    ids = [d.id for d in due]
    for d in due:
        d.next_attempt_at = now + LEASE
    session.commit()
    return ids


def process_due_deliveries(session, now: datetime | None = None) -> int:
    """
    Attempt every pending delivery that is due, once. Returns the count claimed.
    A failure of any kind in one delivery is recorded on that row (attempt counted, backoff,
    `failed` after MAX_ATTEMPTS) and never stops the rest of the batch.
    """
    now = now or datetime.now(timezone.utc)
    ids = claim_due_deliveries(session, now)
    for delivery_id in ids:
        try:
            row = session.get(WebhookDelivery, delivery_id)
            if row is None:
                continue
            attempt_delivery(session, row, now)
            session.commit()
        except Exception as err:
            session.rollback()
            logger.warning('Delivery %s failed: %s', delivery_id, error_label(err))
            record_failure(session, delivery_id, now, err)
    return len(ids)


def error_label(err: Exception) -> str:
    """Short, secret-free description: the class name, plus the status for HTTP errors."""
    response = getattr(err, 'response', None)
    if isinstance(err, requests.HTTPError) and response is not None:
        return f'HTTPError {response.status_code}'
    return type(err).__name__


def record_failure(session, delivery_id: int, now: datetime, err: Exception) -> None:
    row = session.get(WebhookDelivery, delivery_id)
    if row is None:
        return
    row.attempts += 1
    row.last_error = error_label(err)
    if row.attempts >= MAX_ATTEMPTS:
        row.status = FAILED
        row.next_attempt_at = None
    else:
        row.next_attempt_at = now + BACKOFF_BASE * 2 ** (row.attempts - 1)
    session.commit()


def attempt_delivery(session, delivery: WebhookDelivery, now: datetime) -> None:
    """POST one delivery. Marks it delivered on success; raises on any failure (caller records)."""
    webhook = session.get(Webhook, delivery.webhook_id)
    pr = session.get(MirroredPullRequest, delivery.mirrored_pull_request_id)
    if webhook is None or pr is None:
        raise LookupError('webhook or pull request no longer exists')
    mirror = session.get(Mirror, pr.mirror_id)
    post_event(webhook, build_event(delivery.delivery_uuid, mirror, pr))
    delivery.attempts += 1
    delivery.status = DELIVERED
    delivery.next_attempt_at = None
    delivery.last_error = None


def requeue_failed(session, webhook_id: int | None = None, now: datetime | None = None) -> int:
    """
    Put `failed` deliveries back in the queue (attempts reset, due now), optionally only those of
    one webhook, and commit. Returns the number requeued. Meant for an operator after a receiver
    outage longer than the retry window; there is deliberately no API route for it yet:
    call it from a shell in the pod, e.g.
    `python -c "from app import create_app, delivery; from app.helpers.base_model import db;
    app = create_app(); app.app_context().push(); print(delivery.requeue_failed(db.session))"`.
    """
    stmt = update(WebhookDelivery).where(WebhookDelivery.status == FAILED)
    if webhook_id is not None:
        stmt = stmt.where(WebhookDelivery.webhook_id == webhook_id)
    result = session.execute(stmt.values(
        status=PENDING, attempts=0, last_error=None, next_attempt_at=now or datetime.now(timezone.utc),
    ).execution_options(synchronize_session='fetch'))
    session.commit()
    return result.rowcount
