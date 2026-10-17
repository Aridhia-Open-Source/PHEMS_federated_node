"""Outbox hardening: poison deliveries, leasing, redirects, ids, schema drift, loop health."""
import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import responses
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import delivery, runner
from app.helpers.base_model import Base, db, engine
from app.models.mirror import Mirror, MirrorState, MirroredPullRequest, Webhook, WebhookDelivery

URL = 'http://receiver.test/hook'
KEY = 'k'


def make_mirror(n=1):
    m = Mirror(upstream_uri=f'https://github.com/org/r{n}', secret_namespace='ns', secret_key='t',
               gitea_owner='org', gitea_repo=f'r{n}', base_branch='main', enabled=True)
    db.session.add(m)
    db.session.commit()
    return m


def make_pr(mirror, number=7):
    pr = MirroredPullRequest(
        mirror_id=mirror.id, number=number, merge_commit_sha='abc',
        merged_at=datetime(2025, 1, 30, tzinfo=timezone.utc), author='a', gitea_pr_number=1, title='t')
    db.session.add(pr)
    db.session.commit()
    return pr


def make_webhook(url=URL, key='hmac', **over):
    w = Webhook(url=url, secret_namespace='ns', secret_key=key, **over)
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture(autouse=True)
def clean(client, monkeypatch):
    monkeypatch.setattr(delivery, 'read_hmac_key', lambda ns, key: KEY)
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE webhooks CASCADE'))


def queue(webhook, mirror, number=7):
    [d] = delivery.enqueue_deliveries(db.session, make_pr(mirror, number))
    # enqueue only targets enabled webhooks; make sure ours was picked up
    db.session.commit()
    return d


# --- (4) poison delivery -------------------------------------------------

@responses.activate
def test_bad_secret_does_not_block_healthy_webhook(monkeypatch):
    def read_key(ns, key):
        if key == 'bad':
            raise KeyError('token')
        return KEY
    monkeypatch.setattr(delivery, 'read_hmac_key', read_key)
    mirror = make_mirror()
    bad = make_webhook(url='http://bad.test/h', key='bad')
    good = make_webhook(url='http://good.test/h', key='good')
    pr = make_pr(mirror)
    delivery.enqueue_deliveries(db.session, pr)
    db.session.commit()
    responses.post('http://good.test/h', status=200)
    now = datetime.now(timezone.utc)
    for _ in range(delivery.MAX_ATTEMPTS):
        delivery.process_due_deliveries(db.session, now)
        now += timedelta(days=1)
    rows = {r.webhook_id: r for r in db.session.query(WebhookDelivery).all()}
    assert rows[good.id].status == 'delivered'
    assert rows[bad.id].status == 'failed'
    assert rows[bad.id].attempts == delivery.MAX_ATTEMPTS
    assert rows[bad.id].last_error == 'KeyError'
    assert rows[bad.id].next_attempt_at is None


@responses.activate
def test_unexpected_error_is_persisted_as_class_name(monkeypatch):
    d = queue(make_webhook(), make_mirror())

    def boom(*a):
        raise AttributeError("'NoneType' has no attribute 'mirror_id' secret-value")
    monkeypatch.setattr(delivery, 'build_event', boom)
    assert delivery.process_due_deliveries(db.session) == 1
    row = db.session.get(WebhookDelivery, d.id)
    assert row.attempts == 1 and row.status == 'pending' and row.next_attempt_at is not None
    assert row.last_error == 'AttributeError'  # class only: messages may carry secrets


# --- (5) leasing ---------------------------------------------------------

@responses.activate
def test_two_runners_post_each_delivery_once():
    mirror = make_mirror()
    w = make_webhook()
    for n in range(50):
        queue(w, mirror, number=n + 1)
    seen = []
    second = Session(engine)
    state = {'nested': False}

    def cb(request):
        seen.append(request.headers[delivery.DELIVERY_HEADER])
        if len(seen) == 2 and not state['nested']:  # the other runner fires mid-batch, after A's first commit
            state['nested'] = True
            delivery.process_due_deliveries(second)
        return 200, {}, ''
    responses.add_callback(responses.POST, URL, callback=cb)
    delivery.process_due_deliveries(db.session)
    second.close()
    assert len(seen) == 50
    assert len(set(seen)) == 50
    assert db.session.query(WebhookDelivery).filter_by(status='delivered').count() == 50


@responses.activate
def test_lease_expires_so_crashed_runner_rows_retry():
    mirror = make_mirror()
    d = queue(make_webhook(), mirror)
    now = datetime.now(timezone.utc)
    # Claim without finishing (as if the runner died): lease pushes next_attempt_at out.
    claimed = delivery.claim_due_deliveries(db.session, now)
    assert claimed == [d.id]
    assert delivery.process_due_deliveries(db.session, now) == 0
    responses.post(URL, status=200)
    assert delivery.process_due_deliveries(db.session, now + delivery.LEASE + timedelta(seconds=1)) == 1


# --- (15) redirects, requeue, ids, timestamp -----------------------------

@responses.activate
def test_redirect_is_not_followed_and_is_a_failure():
    mirror = make_mirror()
    d = queue(make_webhook(), mirror)
    responses.post(URL, status=302, headers={'Location': 'http://internal.test/x'})
    responses.post('http://internal.test/x', status=200)
    delivery.process_due_deliveries(db.session)
    assert [c.request.url for c in responses.calls] == [URL]
    row = db.session.get(WebhookDelivery, d.id)
    assert row.status == 'pending' and row.attempts == 1 and 'HTTPError' in row.last_error


def test_requeue_failed():
    mirror = make_mirror()
    w1, w2 = make_webhook(), make_webhook()
    pr = make_pr(mirror)
    ds = delivery.enqueue_deliveries(db.session, pr)
    for d in ds:
        d.status, d.attempts, d.next_attempt_at, d.last_error = 'failed', 5, None, 'X'
    db.session.commit()
    now = datetime.now(timezone.utc)
    assert delivery.requeue_failed(db.session, webhook_id=w1.id, now=now) == 1
    rows = {d.webhook_id: d for d in db.session.query(WebhookDelivery).all()}
    assert rows[w1.id].status == 'pending' and rows[w1.id].attempts == 0
    assert rows[w1.id].next_attempt_at == now and rows[w1.id].last_error is None
    assert rows[w2.id].status == 'failed'
    assert delivery.requeue_failed(db.session) == 1
    assert db.session.query(WebhookDelivery).filter_by(status='failed').count() == 0


@responses.activate
def test_stable_uuid_and_timestamp_header():
    mirror = make_mirror()
    d = queue(make_webhook(), mirror)
    responses.post(URL, status=200)
    delivery.process_due_deliveries(db.session)
    req = responses.calls[0].request
    db.session.refresh(d)
    assert d.delivery_uuid and d.delivery_uuid != str(d.id)
    assert req.headers[delivery.DELIVERY_HEADER] == d.delivery_uuid
    assert json.loads(req.body)['delivery_id'] == d.delivery_uuid
    assert abs(int(req.headers[delivery.TIMESTAMP_HEADER]) - time.time()) < 60
    # The signed bytes stay the documented HMAC over the body only.
    assert req.headers[delivery.SIGNATURE_HEADER] == (
        'sha256=' + hmac.new(KEY.encode(), req.body, hashlib.sha256).hexdigest())


def test_delivery_uuids_are_unique():
    mirror = make_mirror()
    make_webhook(), make_webhook()
    ds = delivery.enqueue_deliveries(db.session, make_pr(mirror))
    db.session.commit()
    assert len({d.delivery_uuid for d in ds}) == 2


# --- (15)/(19) schema ----------------------------------------------------

def test_indexes_exist():
    insp = inspect(engine)
    cols = [tuple(i['column_names']) for i in insp.get_indexes('webhook_deliveries')]
    assert ('status', 'next_attempt_at') in cols
    assert ('webhook_id',) in cols and ('mirrored_pull_request_id',) in cols


def test_model_and_migration_have_no_drift():
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_unique_owner_repo_in_model():
    names = {tuple(c.columns.keys()) for c in Mirror.__table__.constraints
             if c.__class__.__name__ == 'UniqueConstraint'}
    assert ('gitea_owner', 'gitea_repo') in names


def test_status_check_constraint():
    mirror = make_mirror()
    w = make_webhook()
    pr = make_pr(mirror)
    db.session.add(WebhookDelivery(webhook_id=w.id, mirrored_pull_request_id=pr.id, status='bogus'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_cursor_not_null():
    m = make_mirror()
    with pytest.raises(IntegrityError):  # explicit NULL, bypassing the ORM's default handling
        db.session.execute(text('INSERT INTO mirror_state (mirror_id, cursor) VALUES (:i, NULL)'), {'i': m.id})
    db.session.rollback()
    db.session.add(MirrorState(mirror_id=m.id))
    db.session.commit()
    assert db.session.get(MirrorState, m.id).cursor is not None


# --- (12) health and tick isolation --------------------------------------

def test_health_without_loop_registered_is_ok(client):
    assert client.get('/health').status_code == 200


def _status(client, alive, age, interval=10):
    st = runner.LoopStatus(interval=interval)
    st.last_tick_at = datetime.now(timezone.utc) - timedelta(seconds=age)
    st.thread = type('T', (), {'is_alive': lambda self: alive})()
    client.application.extensions['sync_status'] = st
    return st


def test_health_reports_loop_state(client):
    _status(client, alive=True, age=5)
    res = client.get('/health')
    assert res.status_code == 200
    assert res.get_json()['sync']['alive'] is True and res.get_json()['sync']['last_tick_at']
    _status(client, alive=False, age=5)
    assert client.get('/health').status_code == 503
    _status(client, alive=True, age=31)
    assert client.get('/health').status_code == 503
    client.application.extensions.pop('sync_status')


def test_loop_thread_updates_heartbeat(client):
    app = client.application
    st = runner.LoopStatus(interval=1)
    stop = threading.Event()
    ticks = []
    st.thread = threading.Thread(
        target=runner.run_loop, args=(app, st), kwargs={'tick_fn': lambda a, p, s: ticks.append(1),
                                                       'stop': stop, 'sleep': lambda s: stop.set()})
    st.thread.start()
    st.thread.join(5)
    assert ticks == [1] and st.last_tick_at is not None


def test_one_failing_mirror_does_not_stop_the_next(client, monkeypatch):
    m1, m2 = make_mirror(1), make_mirror(2)
    called = []

    def fake_resync(mirror_id, *a):
        called.append(mirror_id)
        if mirror_id == m1.id:
            try:
                db.session.execute(text('SELECT * FROM no_such_table'))
            except Exception:
                pass  # leaves the transaction aborted, as a half-failed sync can
            raise RuntimeError('boom')
        db.session.execute(text('SELECT 1'))  # fails if the session is still poisoned
        return []
    monkeypatch.setattr(runner, 'resync', fake_resync)
    st = runner.LoopStatus(interval=10)
    runner.tick(client.application, {}, st)
    assert called == [m1.id, m2.id]
    assert st.last_tick_at is not None
