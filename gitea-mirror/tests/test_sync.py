"""Sync engine unit tests: errors, rate-limit pause, lock, cursor. Gitea-backed replay is in
test_sync_gitea.py."""
from datetime import datetime, timedelta, timezone

import pytest
import responses
from sqlalchemy import text
from sqlalchemy.orm.session import close_all_sessions

from app import create_app, github, sync
from app.gitea import shadow_login
from app.github import GithubRestClient
from app.helpers.base_model import db, engine
from app.models.mirror import Mirror, MirrorState

PULLS = 'https://api.github.com/repos/org/repo/pulls'
CURSOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setattr(github, 'read_secret_token', lambda ns, key: 'ghp_test')


@pytest.fixture
def app(migrated, gitea, tmp_path):
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE mirrors CASCADE'))
    app = create_app(
        github_client=GithubRestClient(), gitea_client=gitea,
        git_cache=sync.GitCache(str(tmp_path)),
    )
    app.testing = True
    with app.app_context():
        yield app
        close_all_sessions()


@pytest.fixture
def mirror_id(app):
    mirror = Mirror(
        upstream_uri='https://github.com/org/repo', secret_namespace='ns', secret_key='key',
        gitea_owner='org', gitea_repo='repo', base_branch='main', enabled=True,
    )
    db.session.add(mirror)
    db.session.flush()
    db.session.add(MirrorState(mirror_id=mirror.id, cursor=CURSOR))
    db.session.commit()
    return mirror.id


def state(mirror_id):
    db.session.expire_all()
    return db.session.get(MirrorState, mirror_id)


@responses.activate
def test_token_expired_recorded_and_flagged(app, auth, mirror_id):
    responses.get(PULLS, status=401, json={'message': 'Bad credentials'})
    with app.test_client() as client:
        resp = client.post(f'/mirrors/{mirror_id}/resync', headers=auth)
        assert resp.status_code == 502
        assert 'token_expired' in resp.get_json()['error']
        status = client.get(f'/mirrors/{mirror_id}/status', headers=auth).get_json()
    assert status['token_expired'] is True
    assert status['last_sync_at'] is not None
    assert status['last_success_at'] is None
    assert state(mirror_id).cursor == CURSOR


@responses.activate
def test_rate_limit_pauses_mirror_until_reset(app, mirror_id):
    reset = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    responses.get(PULLS, status=403, json={'message': 'rate limit'},
                  headers={'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(reset)})
    paused = {}
    sync.tick(app, paused)
    assert paused == {mirror_id: datetime.fromtimestamp(reset, tz=timezone.utc)}
    assert 'rate limit' in state(mirror_id).last_error
    assert len(responses.calls) == 1

    sync.tick(app, paused)  # still paused: GitHub is not called
    assert len(responses.calls) == 1

    paused[mirror_id] = datetime.now(timezone.utc) - timedelta(seconds=1)
    sync.tick(app, paused)  # reset passed: tries again
    assert len(responses.calls) == 2


def test_resync_busy_when_locked(app, auth, mirror_id):
    with engine.connect() as other:
        other.execute(text('SELECT pg_advisory_lock(:ns, :id)'),
                      {'ns': sync.LOCK_NAMESPACE, 'id': mirror_id})
        with app.test_client() as client:
            assert client.post(f'/mirrors/{mirror_id}/resync', headers=auth).status_code == 409
        other.execute(text('SELECT pg_advisory_unlock(:ns, :id)'),
                      {'ns': sync.LOCK_NAMESPACE, 'id': mirror_id})


def test_advance_cursor_stops_at_first_unmirrored_by_updated_at():
    pulls = [
        {'number': 1, 'updated_at': '2026-03-05T00:00:00Z'},
        {'number': 2, 'updated_at': '2026-03-02T00:00:00Z'},
        {'number': 3, 'updated_at': '2026-03-03T00:00:00Z'},
    ]
    st = MirrorState(cursor=CURSOR)
    sync.advance_cursor(st, pulls, {1})  # 1 done but 2 (updated earlier) not: stay
    assert st.cursor == CURSOR
    sync.advance_cursor(st, pulls, {1, 2})
    assert st.cursor == datetime(2026, 3, 2, tzinfo=timezone.utc)
    sync.advance_cursor(st, pulls, {1, 2, 3})
    assert st.cursor == datetime(2026, 3, 5, tzinfo=timezone.utc)


def test_git_error_hides_auth_header(tmp_path):
    with pytest.raises(sync.GitError) as err:
        sync.run_git(['fetch', str(tmp_path / 'missing')], cwd=str(tmp_path),
                     authorization='Basic c2VjcmV0')
    assert 'c2VjcmV0' not in str(err.value)


@pytest.mark.parametrize('login,shadow', [
    ('alice', 'alice'), ('dependabot[bot]', 'dependabot-bot'), ('a.b_c-d', 'a.b_c-d'),
])
def test_shadow_login(login, shadow):
    assert shadow_login(login) == shadow
