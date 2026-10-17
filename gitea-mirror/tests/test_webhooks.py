import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import responses
from jsonschema import Draft202012Validator, FormatChecker

from app import delivery, webhooks as webhooks_module
from app.helpers.base_model import db
from app.models.mirror import Mirror, MirroredPullRequest, Webhook, WebhookDelivery

SCHEMA = json.loads(
    (Path(__file__).parent.parent / 'schema' / 'pull_request.mirrored.json').read_text()
)
URL = 'http://receiver.test/hook'
KEY = 'hmac-secret'
BODY = {'url': URL, 'secret_namespace': 'ns', 'secret_key': 'hmac'}


@pytest.fixture(autouse=True)
def hmac_key(monkeypatch):
    monkeypatch.setattr(delivery, 'read_hmac_key', lambda namespace, key: KEY)


FAKE_DNS = {
    'receiver.test': ['10.1.2.3'],
    'svc.ns.svc.cluster.local': ['10.96.0.20'],
    'public.test': ['93.184.216.34'],
    'loop.test': ['127.0.0.1'],
    'meta.test': ['169.254.169.254'],
    'mixed.test': ['10.1.2.3', '127.0.0.1'],
    'v6loop.test': ['::1'],
    'unspec.test': ['0.0.0.0'],
    'kubernetes.default.svc': ['10.96.0.1'],
}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    def resolve(host):
        if host in FAKE_DNS:
            return FAKE_DNS[host]
        raise OSError('no such host')
    monkeypatch.setattr(webhooks_module, 'resolve_host', resolve)


def make_mirror(n=1):
    mirror = Mirror(
        upstream_uri=f'https://github.com/org/repo{n}', secret_namespace='ns', secret_key='t',
        gitea_owner='org', gitea_repo=f'repo{n}', base_branch='main', enabled=True,
    )
    db.session.add(mirror)
    db.session.commit()
    return mirror


def make_pr(mirror, number=7):
    pr = MirroredPullRequest(
        mirror_id=mirror.id, number=number, merge_commit_sha='abc123',
        merged_at=datetime(2025, 1, 30, 19, 3, 52, tzinfo=timezone.utc), author='alice',
        gitea_pr_number=1, title='Fix it',
    )
    db.session.add(pr)
    db.session.commit()
    return pr


def make_webhook(client, auth, **over):
    return client.post('/webhooks', json={**BODY, **over}, headers=auth)


def validate(event):
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(event)


def test_create_defaults_and_serializes(client, auth):
    res = make_webhook(client, auth)
    assert res.status_code == 201
    assert res.json == {'id': res.json['id'], **BODY, 'mirror_id': None, 'enabled': True}
    assert client.get('/webhooks', headers=auth).json == [res.json]
    assert client.get(f'/webhooks/{res.json["id"]}', headers=auth).json == res.json


@pytest.mark.parametrize('method,path', [
    ('get', '/webhooks'), ('post', '/webhooks'), ('get', '/webhooks/1'),
    ('patch', '/webhooks/1'), ('delete', '/webhooks/1'), ('post', '/webhooks/1/test'),
    ('get', '/webhooks/1/deliveries'),
])
def test_auth_required(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize('over', [
    {'url': 'ftp://x/y'}, {'url': ''}, {'secret_key': 5}, {'enabled': 'yes'},
    {'mirror_id': 'a'}, {'mirror_id': 9999}, {'extra': 1},
])
def test_create_validation_400(client, auth, over):
    assert make_webhook(client, auth, **over).status_code == 400


def test_create_missing_fields_400(client, auth):
    assert client.post('/webhooks', json={'url': URL}, headers=auth).status_code == 400
    assert client.post('/webhooks', json=[], headers=auth).status_code == 400


def test_404s(client, auth):
    for call in (client.get, client.patch, client.delete):
        assert call('/webhooks/999', headers=auth).status_code == 404
    assert client.post('/webhooks/999/test', headers=auth).status_code == 404
    assert client.get('/webhooks/999/deliveries', headers=auth).status_code == 404


def test_patch_and_delete(client, auth):
    mirror = make_mirror()
    wid = make_webhook(client, auth).json['id']
    res = client.patch(f'/webhooks/{wid}', json={'enabled': False, 'mirror_id': mirror.id}, headers=auth)
    assert res.status_code == 200
    assert res.json['enabled'] is False and res.json['mirror_id'] == mirror.id
    assert client.patch(f'/webhooks/{wid}', json={'url': 'nope'}, headers=auth).status_code == 400
    assert client.delete(f'/webhooks/{wid}', headers=auth).status_code == 204
    assert client.get(f'/webhooks/{wid}', headers=auth).status_code == 404


def test_deleting_mirror_cascades_scoped_webhook(client, auth):
    mirror = make_mirror()
    wid = make_webhook(client, auth, mirror_id=mirror.id).json['id']
    db.session.delete(mirror)
    db.session.commit()
    assert client.get(f'/webhooks/{wid}', headers=auth).status_code == 404


def test_enqueue_matches_enabled_and_scope(client, auth):
    m1, m2 = make_mirror(1), make_mirror(2)
    all_id = make_webhook(client, auth).json['id']
    own_id = make_webhook(client, auth, mirror_id=m1.id).json['id']
    make_webhook(client, auth, mirror_id=m2.id)
    make_webhook(client, auth, enabled=False)
    pr = make_pr(m1)
    created = delivery.enqueue_deliveries(db.session, pr)
    db.session.commit()
    assert sorted(d.webhook_id for d in created) == sorted([all_id, own_id])
    assert all(d.status == 'pending' and d.attempts == 0 and d.next_attempt_at for d in created)


def pending_delivery(client, auth):
    mirror = make_mirror()
    wid = make_webhook(client, auth).json['id']
    [d] = delivery.enqueue_deliveries(db.session, make_pr(mirror))
    db.session.commit()
    return wid, d.id


@responses.activate
def test_delivery_signed_and_schema_valid(client, auth):
    wid, did = pending_delivery(client, auth)
    responses.post(URL, status=200)
    assert delivery.process_due_deliveries(db.session) == 1
    req = responses.calls[0].request
    expected = 'sha256=' + hmac.new(KEY.encode(), req.body, hashlib.sha256).hexdigest()
    assert req.headers[delivery.SIGNATURE_HEADER] == expected
    assert req.headers[delivery.DELIVERY_HEADER] == str(did)
    event = json.loads(req.body)
    validate(event)
    assert event['delivery_id'] == str(did)
    assert event['number'] == 7 and event['gitea_pr_number'] == 1
    assert event['mirror'] == {
        'upstream_uri': 'https://github.com/org/repo1', 'gitea_owner': 'org', 'gitea_repo': 'repo1',
    }
    row = db.session.get(WebhookDelivery, did)
    assert row.status == 'delivered' and row.attempts == 1 and row.last_error is None
    assert delivery.process_due_deliveries(db.session) == 0


def test_schema_rejects_bad_events():
    good = {
        'event': 'pull_request.mirrored', 'delivery_id': '1',
        'mirror': {'upstream_uri': 'u', 'gitea_owner': 'o', 'gitea_repo': 'r'},
        'number': 1, 'gitea_pr_number': 2, 'title': 't', 'author': 'a',
        'merged_at': '2025-01-30T19:03:52+00:00', 'merge_commit_sha': 'abc',
    }
    validate(good)
    for bad in ({**good, 'event': 'x'}, {**good, 'merged_at': 'yesterday'}, {**good, 'extra': 1},
                {k: v for k, v in good.items() if k != 'gitea_pr_number'}):
        with pytest.raises(Exception):
            validate(bad)


@responses.activate
def test_retry_with_backoff_then_success(client, auth):
    _, did = pending_delivery(client, auth)
    now = datetime.now(timezone.utc)
    responses.post(URL, status=500)
    assert delivery.process_due_deliveries(db.session, now) == 1
    row = db.session.get(WebhookDelivery, did)
    assert row.status == 'pending' and row.attempts == 1 and '500' in row.last_error
    assert row.next_attempt_at == now + delivery.BACKOFF_BASE
    # Not due yet.
    assert delivery.process_due_deliveries(db.session, now + delivery.BACKOFF_BASE / 2) == 0
    # Second failure doubles the wait.
    later = now + delivery.BACKOFF_BASE
    assert delivery.process_due_deliveries(db.session, later) == 1
    db.session.refresh(row)
    assert row.attempts == 2 and row.next_attempt_at == later + delivery.BACKOFF_BASE * 2
    responses.replace(responses.POST, URL, status=204)
    assert delivery.process_due_deliveries(db.session, row.next_attempt_at) == 1
    db.session.refresh(row)
    assert row.status == 'delivered' and row.attempts == 3 and row.last_error is None


@responses.activate
def test_failed_after_max_attempts(client, auth):
    wid, did = pending_delivery(client, auth)
    responses.post(URL, body=requests.ConnectionError('refused'))
    now = datetime.now(timezone.utc)
    for _ in range(delivery.MAX_ATTEMPTS):
        assert delivery.process_due_deliveries(db.session, now) == 1
        now += timedelta(days=1)
    row = db.session.get(WebhookDelivery, did)
    assert row.status == 'failed' and row.attempts == delivery.MAX_ATTEMPTS
    assert row.next_attempt_at is None and 'refused' in row.last_error
    assert delivery.process_due_deliveries(db.session, now) == 0
    listed = client.get(f'/webhooks/{wid}/deliveries?status=failed', headers=auth).json
    assert [d['id'] for d in listed] == [did] and listed[0]['status'] == 'failed'


@responses.activate
def test_secret_read_failure_counts_as_failed_attempt(client, auth, monkeypatch):
    _, did = pending_delivery(client, auth)

    def boom(namespace, key):
        raise requests.HTTPError('secret not found')

    monkeypatch.setattr(delivery, 'read_hmac_key', boom)
    assert delivery.process_due_deliveries(db.session) == 1
    row = db.session.get(WebhookDelivery, did)
    assert row.attempts == 1 and 'secret not found' in row.last_error
    assert len(responses.calls) == 0


@responses.activate
def test_deliveries_listing_newest_first(client, auth):
    mirror = make_mirror()
    wid = make_webhook(client, auth).json['id']
    for n in (1, 2):
        delivery.enqueue_deliveries(db.session, make_pr(mirror, number=n))
    db.session.commit()
    listed = client.get(f'/webhooks/{wid}/deliveries', headers=auth).json
    assert len(listed) == 2 and listed[0]['id'] > listed[1]['id']
    assert set(listed[0]) == {
        'id', 'webhook_id', 'mirrored_pull_request_id', 'status', 'attempts',
        'next_attempt_at', 'last_error',
    }


@responses.activate
def test_test_ping_signed(client, auth):
    wid = make_webhook(client, auth).json['id']
    responses.post(URL, status=200)
    res = client.post(f'/webhooks/{wid}/test', headers=auth)
    assert res.status_code == 200 and res.json == {'status': 'ok'}
    req = responses.calls[0].request
    assert req.headers[delivery.SIGNATURE_HEADER] == delivery.sign(req.body, KEY)
    assert json.loads(req.body)['event'] == 'ping'
    assert req.headers[delivery.EVENT_HEADER] == 'ping'


@responses.activate
def test_test_ping_receiver_failure_502(client, auth):
    wid = make_webhook(client, auth).json['id']
    responses.post(URL, status=503)
    res = client.post(f'/webhooks/{wid}/test', headers=auth)
    assert res.status_code == 502 and res.json['status'] == 'failed'


# --- registration-time validation (review findings 8 and 14) ---

@pytest.mark.parametrize('url', [
    'http://user:pw@receiver.test/hook', 'http://user@receiver.test/hook',
    'http://127.0.0.1/hook', 'http://127.0.0.1:8080/hook', 'http://[::1]/hook', 'http://localhost/hook',
    'http://169.254.169.254/latest/meta-data', 'http://[fe80::1]/hook', 'http://0.0.0.0/hook',
    'http://[::]/hook', 'http://[::ffff:127.0.0.1]/hook', 'http://[::ffff:169.254.169.254]/hook',
    'http://2130706433/hook', 'http://loop.test/hook', 'http://meta.test/hook',
    'http://mixed.test/hook', 'http://v6loop.test/hook', 'http://unspec.test/hook',
    'http://unresolvable.test/hook', 'http://kubernetes.default.svc/api',
    'http://receiver.test:99999/hook', 'http:///hook', 'http://receiver.test/hook\nx',
    'http://rec eiver.test/hook',
])
def test_webhook_url_policy_rejects(client, auth, url):
    assert make_webhook(client, auth, url=url).status_code == 400
    assert client.get('/webhooks', headers=auth).json == []


def test_webhook_url_rejects_kubernetes_service_host(client, auth, monkeypatch):
    monkeypatch.setenv('KUBERNETES_SERVICE_HOST', '10.96.0.1')
    monkeypatch.setitem(FAKE_DNS, 'alias.test', ['10.96.0.1'])
    assert make_webhook(client, auth, url='http://alias.test/x').status_code == 400
    assert make_webhook(client, auth, url='http://10.96.0.1/x').status_code == 400


@pytest.mark.parametrize('url', [
    'http://receiver.test/hook', 'https://receiver.test:8443/hook', 'http://svc.ns.svc.cluster.local/hook',
    'http://10.0.0.5:8080/hook', 'https://public.test/hook',
])
def test_webhook_url_policy_allows_cluster_and_public(client, auth, url):
    assert make_webhook(client, auth, url=url).status_code == 201


def test_webhook_private_ranges_can_be_disabled(client, auth, monkeypatch):
    monkeypatch.setenv('GITEA_MIRROR_WEBHOOK_ALLOW_PRIVATE', 'false')
    assert make_webhook(client, auth, url='http://receiver.test/hook').status_code == 400
    assert make_webhook(client, auth, url='http://10.0.0.5/hook').status_code == 400
    assert make_webhook(client, auth, url='https://public.test/hook').status_code == 201
    monkeypatch.setenv('GITEA_MIRROR_WEBHOOK_ALLOW_PRIVATE', 'true')
    assert make_webhook(client, auth, url='http://receiver.test/hook').status_code == 201


def test_webhook_loopback_never_allowed_even_with_allow_private(client, auth, monkeypatch):
    monkeypatch.setenv('GITEA_MIRROR_WEBHOOK_ALLOW_PRIVATE', 'true')
    assert make_webhook(client, auth, url='http://127.0.0.1/x').status_code == 400
    assert make_webhook(client, auth, url='http://169.254.169.254/x').status_code == 400


def test_patch_url_is_revalidated(client, auth):
    wid = make_webhook(client, auth).json['id']
    res = client.patch(f'/webhooks/{wid}', json={'url': 'http://169.254.169.254/x'}, headers=auth)
    assert res.status_code == 400
    assert client.get(f'/webhooks/{wid}', headers=auth).json['url'] == URL


@pytest.mark.parametrize('over', [
    {'secret_namespace': '../kube-system'}, {'secret_key': 'x/../..'}, {'secret_key': 'a:b'},
    {'secret_namespace': 'A b'}, {'secret_key': 'x' * 254},
])
def test_webhook_secret_ref_whitelist(client, auth, over):
    assert make_webhook(client, auth, **over).status_code == 400
    wid = make_webhook(client, auth).json['id']
    assert client.patch(f'/webhooks/{wid}', json=over, headers=auth).status_code == 400


def test_webhook_secret_must_exist_at_registration(client, auth, monkeypatch):
    seen = []

    def read(namespace, key):
        seen.append((namespace, key))
        raise KeyError('token')
    monkeypatch.setattr(delivery, 'read_hmac_key', read)
    res = make_webhook(client, auth)
    assert res.status_code == 400 and 'secret' in res.json['error'].lower()
    assert seen == [('ns', 'hmac')]
    assert client.get('/webhooks', headers=auth).json == []


@pytest.mark.parametrize('exc', [
    FileNotFoundError('/var/run/secrets/token'), requests.HTTPError('404 secrets "hmac" not found'),
    requests.ConnectionError('boom'), ValueError('bad base64'),
])
def test_webhook_secret_read_errors_are_400_without_leak(client, auth, monkeypatch, exc):
    def read(namespace, key):
        raise exc
    monkeypatch.setattr(delivery, 'read_hmac_key', read)
    res = make_webhook(client, auth)
    assert res.status_code == 400
    assert str(exc) not in res.get_data(as_text=True)


def test_webhook_empty_secret_is_rejected(client, auth, monkeypatch):
    monkeypatch.setattr(delivery, 'read_hmac_key', lambda n, k: '')
    assert make_webhook(client, auth).status_code == 400


def test_patch_secret_ref_is_revalidated_and_unrelated_patch_is_not(client, auth, monkeypatch):
    wid = make_webhook(client, auth).json['id']

    def read(namespace, key):
        raise KeyError('token')
    monkeypatch.setattr(delivery, 'read_hmac_key', read)
    assert client.patch(f'/webhooks/{wid}', json={'secret_key': 'other'}, headers=auth).status_code == 400
    assert client.patch(f'/webhooks/{wid}', json={'enabled': False}, headers=auth).status_code == 200


# --- test ping (finding 8) ---

@responses.activate
def test_test_ping_does_not_leak_exception_text(client, auth):
    wid = make_webhook(client, auth).json['id']
    responses.post(URL, body=requests.ConnectionError('HTTPConnectionPool(host=10.1.2.3): refused'))
    res = client.post(f'/webhooks/{wid}/test', headers=auth)
    assert res.status_code == 502
    assert res.json == {'status': 'failed', 'reason': 'ConnectionError'}
    assert '10.1.2.3' not in res.get_data(as_text=True)


@responses.activate
def test_test_ping_http_error_reports_class_only(client, auth):
    wid = make_webhook(client, auth).json['id']
    responses.post(URL, status=503)
    res = client.post(f'/webhooks/{wid}/test', headers=auth)
    assert res.status_code == 502
    assert res.json == {'status': 'failed', 'reason': 'HTTPError'}


@responses.activate
def test_test_ping_secret_error_is_generic(client, auth, monkeypatch):
    wid = make_webhook(client, auth).json['id']

    def boom(namespace, key):
        raise KeyError('token')
    monkeypatch.setattr(delivery, 'read_hmac_key', boom)
    res = client.post(f'/webhooks/{wid}/test', headers=auth)
    assert res.status_code == 502 and res.json['status'] == 'failed'
    assert 'token' not in res.get_data(as_text=True)


@responses.activate
def test_test_ping_does_not_follow_redirects(client, auth):
    wid = make_webhook(client, auth).json['id']
    responses.post(URL, status=302, headers={'Location': 'http://169.254.169.254/latest/meta-data'})
    responses.get('http://169.254.169.254/latest/meta-data', body='secret')
    responses.post('http://169.254.169.254/latest/meta-data', body='secret')
    res = client.post(f'/webhooks/{wid}/test', headers=auth)
    assert len(responses.calls) == 1
    assert res.status_code == 502


def test_test_ping_passes_allow_redirects_false(client, auth, monkeypatch):
    wid = make_webhook(client, auth).json['id']
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        resp = requests.Response()
        resp.status_code = 200
        return resp
    monkeypatch.setattr(requests, 'post', fake_post)
    assert client.post(f'/webhooks/{wid}/test', headers=auth).status_code == 200
    assert captured['allow_redirects'] is False


def test_test_ping_revalidates_stored_url(client, auth):
    wid = make_webhook(client, auth).json['id']
    wh = db.session.get(Webhook, wid)
    wh.url = 'http://169.254.169.254/x'
    db.session.commit()
    res = client.post(f'/webhooks/{wid}/test', headers=auth)
    assert res.status_code == 502 and res.json['status'] == 'failed'
    assert res.json['reason'] == 'UrlRejected'
