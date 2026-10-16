import pytest
from app import create_app
from app.helpers.base_model import db
from app.models.mirror import MirrorState, MirroredPullRequest
from datetime import datetime, timezone

BODY = {
    'upstream_uri': 'https://github.com/org/repo',
    'secret_namespace': 'ns',
    'secret_key': 'token',
    'gitea_owner': 'org',
    'gitea_repo': 'repo',
    'base_branch': 'main',
}


def make(client, auth, **over):
    return client.post('/mirrors', json={**BODY, **over}, headers=auth)


def test_missing_token_env_fails_fast(monkeypatch):
    monkeypatch.delenv('GITEA_MIRROR_API_TOKEN')
    with pytest.raises(KeyError):
        create_app()


@pytest.mark.parametrize('method,path', [
    ('get', '/mirrors'), ('post', '/mirrors'), ('get', '/mirrors/1'),
    ('patch', '/mirrors/1'), ('delete', '/mirrors/1'), ('get', '/mirrors/1/status'),
    ('post', '/mirrors/1/resync'), ('post', '/mirrors/1/users/sync'),
])
def test_auth_required(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    bad = {'Authorization': 'Bearer nope'}
    assert getattr(client, method)(path, headers=bad).status_code == 401


def test_health_needs_no_auth(client):
    assert client.get('/health').status_code == 200


def test_create_and_get(client, auth, github):
    resp = make(client, auth)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['enabled'] is True
    assert data['users_sync'] == {'status': 'ok', 'users': 2, 'created': 1, 'existing': 1}
    assert github.calls == [(BODY['upstream_uri'], 'ns', 'token')]
    state = db.session.get(MirrorState, data['id'])
    assert state.cursor is not None and state.cursor <= datetime.now(timezone.utc)

    got = client.get(f'/mirrors/{data["id"]}', headers=auth)
    assert got.status_code == 200 and got.get_json()['gitea_repo'] == 'repo'
    listed = client.get('/mirrors', headers=auth).get_json()
    assert [m['id'] for m in listed] == [data['id']]


def test_create_users_sync_failure_keeps_mirror(client, auth, github):
    github.error = 'rate limited'
    resp = make(client, auth)
    assert resp.status_code == 201
    assert resp.get_json()['users_sync'] == {'status': 'failed', 'reason': 'rate limited'}
    assert len(client.get('/mirrors', headers=auth).get_json()) == 1


def test_create_users_sync_unconfigured(migrated, auth):
    app = create_app()
    app.testing = True
    with app.test_client() as c, app.app_context():
        resp = make(c, auth, upstream_uri='https://github.com/x/unconfigured',
                    gitea_owner='x', gitea_repo='unconfigured')
        assert resp.status_code == 201
        assert resp.get_json()['users_sync']['status'] == 'skipped'


@pytest.mark.parametrize('body', [
    {}, {k: v for k, v in BODY.items() if k != 'base_branch'},
    {**BODY, 'upstream_uri': 'not a url'}, {**BODY, 'upstream_uri': 'http://github.com/o/r'},
    {**BODY, 'gitea_repo': ''}, {**BODY, 'gitea_repo': 5}, {**BODY, 'enabled': 'yes'},
    {**BODY, 'extra': 1}, [],
])
def test_create_bad_input(client, auth, body):
    assert client.post('/mirrors', json=body, headers=auth).status_code == 400


def test_create_not_json(client, auth):
    assert client.post('/mirrors', data='x', headers=auth).status_code == 400


def test_create_conflicts(client, auth):
    assert make(client, auth).status_code == 201
    same_uri = make(client, auth, gitea_owner='o2', gitea_repo='r2')
    assert same_uri.status_code == 409
    same_repo = make(client, auth, upstream_uri='https://github.com/org/other')
    assert same_repo.status_code == 409


def test_get_404(client, auth):
    for method, path in [('get', '/mirrors/999'), ('delete', '/mirrors/999'),
                         ('get', '/mirrors/999/status'), ('post', '/mirrors/999/resync'),
                         ('post', '/mirrors/999/users/sync')]:
        assert getattr(client, method)(path, headers=auth).status_code == 404
    assert client.patch('/mirrors/999', json={}, headers=auth).status_code == 404


def test_patch(client, auth):
    mid = make(client, auth).get_json()['id']
    resp = client.patch(f'/mirrors/{mid}', json={'enabled': False, 'base_branch': 'dev'}, headers=auth)
    assert resp.status_code == 200
    assert resp.get_json()['enabled'] is False and resp.get_json()['base_branch'] == 'dev'
    # patching to its own values is not a conflict
    assert client.patch(f'/mirrors/{mid}', json={'gitea_repo': 'repo'}, headers=auth).status_code == 200


def test_patch_bad_and_conflict(client, auth):
    first = make(client, auth).get_json()['id']
    second = make(client, auth, upstream_uri='https://github.com/org/b', gitea_repo='b').get_json()['id']
    assert client.patch(f'/mirrors/{first}', json={'enabled': 1}, headers=auth).status_code == 400
    assert client.patch(f'/mirrors/{first}', json={'id': 5}, headers=auth).status_code == 400
    r = client.patch(f'/mirrors/{second}', json={'upstream_uri': BODY['upstream_uri']}, headers=auth)
    assert r.status_code == 409
    r = client.patch(f'/mirrors/{second}', json={'gitea_repo': 'repo'}, headers=auth)
    assert r.status_code == 409


def test_delete(client, auth):
    mid = make(client, auth).get_json()['id']
    assert client.delete(f'/mirrors/{mid}', headers=auth).status_code == 204
    assert client.get(f'/mirrors/{mid}', headers=auth).status_code == 404
    assert db.session.get(MirrorState, mid) is None


def test_status(client, auth):
    mid = make(client, auth).get_json()['id']
    data = client.get(f'/mirrors/{mid}/status', headers=auth).get_json()
    assert data['prs_mirrored'] == 0
    assert data['last_error'] is None and data['token_expired'] is False
    assert data['cursor'] is not None


@pytest.mark.parametrize('error,expired', [
    ('connection reset', False),
    ('token_expired: GitHub returned 401', True),
    ('401 Bad credentials', True),
])
def test_status_with_state(client, auth, error, expired):
    mid = make(client, auth).get_json()['id']
    state = db.session.get(MirrorState, mid)
    state.last_error = error
    state.last_sync_at = datetime.now(timezone.utc)
    db.session.add(MirroredPullRequest(
        mirror_id=mid, number=1, merge_commit_sha='abc', merged_at=datetime.now(timezone.utc),
        author='alice', gitea_pr_number=1, title='t'))
    db.session.commit()
    data = client.get(f'/mirrors/{mid}/status', headers=auth).get_json()
    assert data['last_error'] == error
    assert data['token_expired'] is expired
    assert data['prs_mirrored'] == 1
    assert data['last_sync_at'] is not None


def test_resync_not_implemented(client, auth):
    mid = make(client, auth).get_json()['id']
    resp = client.post(f'/mirrors/{mid}/resync', headers=auth)
    assert resp.status_code == 501


def test_users_sync(client, auth, gitea):
    mid = make(client, auth).get_json()['id']
    gitea.users = set()
    resp = client.post(f'/mirrors/{mid}/users/sync', headers=auth)
    assert resp.status_code == 200
    assert resp.get_json() == {'users': 2, 'created': 2, 'existing': 0}
    assert gitea.users == {'alice', 'bob'}


def test_users_sync_client_error(client, auth, github):
    mid = make(client, auth).get_json()['id']
    github.error = 'boom'
    resp = client.post(f'/mirrors/{mid}/users/sync', headers=auth)
    assert resp.status_code == 502


def test_users_sync_unconfigured(migrated, auth):
    app = create_app()
    app.testing = True
    with app.test_client() as c, app.app_context():
        mid = make(c, auth, upstream_uri='https://github.com/x/u2', gitea_owner='x',
                   gitea_repo='u2').get_json()['id']
        assert c.post(f'/mirrors/{mid}/users/sync', headers=auth).status_code == 501
