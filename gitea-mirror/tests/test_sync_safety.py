"""Review findings 3, 7, 9, 13, 14 that need no Gitea: token scoping, credential hygiene, shadow
login naming, cursor semantics, path and ref validation."""
import subprocess
from datetime import datetime, timezone

import pytest
import responses
from sqlalchemy import text
from sqlalchemy.orm.session import close_all_sessions

from app import create_app, github, gitea as gitea_module, sync
from app.github import GithubRestClient, GithubError, repo_path
from app.gitea import HttpGiteaClient, shadow_login
from app.helpers.base_model import db, engine
from app.models.mirror import Mirror, MirrorState

CURSOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setattr(github, 'read_secret_token', lambda ns, key: 'ghp_secret_token')


class Boom(Exception):
    pass


class ExplodingGitea:
    """Any call means the sync went further than it should have."""

    def __getattr__(self, name):
        raise Boom(name)


@pytest.fixture
def make_mirror(migrated, tmp_path):
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE mirrors CASCADE'))
    app = create_app(github_client=GithubRestClient(), gitea_client=ExplodingGitea(),
                     git_cache=sync.GitCache(str(tmp_path)))
    app.testing = True
    ctx = app.app_context()
    ctx.push()

    def make(upstream_uri='https://github.com/org/repo', base_branch='main',
             gitea_owner='org', gitea_repo='repo'):
        mirror = Mirror(
            upstream_uri=upstream_uri, secret_namespace='ns', secret_key='key',
            gitea_owner=gitea_owner, gitea_repo=gitea_repo, base_branch=base_branch, enabled=True,
        )
        db.session.add(mirror)
        db.session.flush()
        db.session.add(MirrorState(mirror_id=mirror.id, cursor=CURSOR))
        db.session.commit()
        return app, mirror.id

    yield make
    close_all_sessions()
    ctx.pop()


def last_error(mirror_id):
    db.session.expire_all()
    return db.session.get(MirrorState, mirror_id).last_error


# ---- 3: the GitHub token only goes to github.com

@pytest.mark.parametrize('uri', [
    'https://evil.example/o/r', 'https://github.com.evil.example/o/r',
    'https://api.github.com/o/r', 'http://github.com/o/r', 'https://github.com:8443/o/r',
    'https://tok:x@github.com/o/r',
])
@responses.activate
def test_sync_refuses_non_github_upstream(make_mirror, uri):
    app, mid = make_mirror(upstream_uri=uri)
    calls = []
    real_run = subprocess.run
    sync.subprocess.run = lambda *a, **k: calls.append(a) or real_run(*a, **k)
    try:
        with pytest.raises(sync.UnsupportedUpstream):
            sync.resync(mid, app.extensions['github_client'], app.extensions['gitea_client'],
                        app.extensions['git_cache'])
    finally:
        sync.subprocess.run = real_run
    assert len(responses.calls) == 0  # nothing sent to GitHub's API or anywhere else
    assert calls == []  # git never ran
    assert 'ghp_secret_token' not in last_error(mid)


def fake_git(monkeypatch):
    seen = []

    def run(cmd, **kwargs):
        seen.append((cmd, kwargs.get('env', {})))
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.setattr(sync.subprocess, 'run', run)
    return seen


def test_github_header_is_scoped_to_github_and_not_in_argv(monkeypatch):
    seen = fake_git(monkeypatch)
    sync.run_git(['fetch', 'https://github.com/o/r'], cwd='/tmp',
                 authorization='Basic c2VjcmV0', auth_scope='https://github.com/')
    cmd, env = seen[0]
    assert 'c2VjcmV0' not in ' '.join(cmd) and 'Authorization' not in ' '.join(cmd)
    assert '-c' not in cmd
    pairs = {env[f'GIT_CONFIG_KEY_{i}']: env[f'GIT_CONFIG_VALUE_{i}']
             for i in range(int(env['GIT_CONFIG_COUNT']))}
    assert pairs['http.https://github.com/.extraHeader'] == 'Authorization: Basic c2VjcmV0'
    assert 'http.extraHeader' not in pairs  # never unscoped
    assert pairs['http.followRedirects'] == 'false'


def test_header_not_sent_to_other_host_for_real(tmp_path):
    """git itself decides: a scoped header must not reach a server at another URL."""
    import http.server
    import threading
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(dict(self.headers))
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(sync.GitError):
            sync.run_git(['ls-remote', f'http://127.0.0.1:{server.server_port}/o/r'],
                         cwd=str(tmp_path), authorization='Basic c2VjcmV0',
                         auth_scope='https://github.com/')
    finally:
        server.shutdown()
    assert received and all('Authorization' not in h for h in received)


# ---- 13: no credentials in argv, errors or last_error

def test_gitea_header_also_via_env_only(monkeypatch):
    seen = fake_git(monkeypatch)
    sync.run_git(['push', 'http://gitea:3000/o/r.git'], cwd='/tmp',
                 authorization='token abc123', auth_scope='http://gitea:3000/')
    cmd, env = seen[0]
    assert 'abc123' not in ' '.join(cmd)
    pairs = {env[f'GIT_CONFIG_KEY_{i}']: env[f'GIT_CONFIG_VALUE_{i}']
             for i in range(int(env['GIT_CONFIG_COUNT']))}
    assert pairs['http.http://gitea:3000/.extraHeader'] == 'Authorization: token abc123'


def test_git_error_never_echoes_credentials(tmp_path):
    with pytest.raises(sync.GitError) as err:
        sync.run_git(['fetch', 'https://user:hunter2@127.0.0.1:1/o/r'], cwd=str(tmp_path),
                     authorization='Basic c2VjcmV0', auth_scope='https://127.0.0.1:1/')
    assert 'hunter2' not in str(err.value) and 'c2VjcmV0' not in str(err.value)


def test_scrub_removes_userinfo_and_secrets():
    text_ = sync.scrub('fatal: https://u:p4ss@h.example/x failed, header Basic c2VjcmV0', ['c2VjcmV0'])
    assert 'p4ss' not in text_ and 'c2VjcmV0' not in text_ and 'h.example' in text_


# ---- 14: validation of names that reach URLs and refspecs

@pytest.mark.parametrize('bad', ['..', '.', 'a/b', 'a b', 'a:b', '', '../admin/users', 'a\n'])
def test_gitea_path_segments_are_validated(bad):
    client = HttpGiteaClient('http://127.0.0.1:1', 'tok')  # nothing listens: must fail before I/O
    with pytest.raises(ValueError):
        client.ensure_org(bad)
    with pytest.raises(ValueError):
        client.ensure_repo('org', bad, 'main')
    with pytest.raises(ValueError):
        client.add_collaborator('org', 'repo', bad)


@pytest.mark.parametrize('bad', ['a:b', 'a b', '../x', 'a..b', '-x', 'a/', '/a', 'a~', 'a^', 'a?', 'a*',
                                 'a[', 'a\\b', 'x.lock', 'a//b', '', 'pr', 'pr/5', 'pr/5/x'])
def test_base_branch_is_validated(bad):
    with pytest.raises(sync.InvalidRefName):
        sync.check_branch_name(bad)


@pytest.mark.parametrize('good', ['main', 'release/1.0', 'feature_x-y', 'pr-5', 'pr/feature', 'v1.2.3'])
def test_valid_branch_names(good):
    sync.check_branch_name(good)


def test_sync_rejects_bad_base_branch_before_any_call(make_mirror):
    app, mid = make_mirror(base_branch='a:b')
    with pytest.raises(sync.InvalidRefName):
        sync.resync(mid, app.extensions['github_client'], app.extensions['gitea_client'],
                    app.extensions['git_cache'])
    assert 'a:b' in last_error(mid)


@pytest.mark.parametrize('uri', ['https://github.com/org/..', 'https://github.com/../repo',
                                 'https://github.com/o r/repo', 'https://github.com/org/re:po'])
def test_repo_path_rejects_odd_segments(uri):
    with pytest.raises(GithubError):
        repo_path(uri)


# ---- 7: shadow user names

def test_shadow_logins_are_prefixed_and_distinct():
    names = [shadow_login(x) for x in ('foo[bot]', 'foo-bot', 'foo', 'testadmin', 'a.b_c-d')]
    assert len(set(names)) == len(names)
    assert all(n.startswith('gh-') for n in names)
    assert shadow_login('alice') == 'gh-alice' and shadow_login('a.b_c-d') == 'gh-a.b_c-d'
    assert shadow_login('foo-bot') == 'gh-foo-bot'
    assert shadow_login('foo[bot]') != shadow_login('foo-bot')


@pytest.mark.parametrize('login', ['', '-', '[bot]', '...', '[]'])
def test_shadow_login_of_empty_result_is_valid(login):
    name = shadow_login(login)
    assert name.startswith('gh-') and len(name) > 3 and name.strip('-.') == name
    assert name == shadow_login(login)  # stable


def test_shadow_login_distinct_for_symbol_only_logins():
    assert shadow_login('[bot]') != shadow_login('[x]')


def test_shadow_login_length_limited():
    assert len(shadow_login('a' * 100)) <= 40
    assert shadow_login('a' * 100) != shadow_login('a' * 99)


def test_sudo_as_non_shadow_user_is_refused():
    client = HttpGiteaClient('http://127.0.0.1:1', 'tok')
    with pytest.raises(ValueError):
        client.open_pull_request('org', 'repo', 'testadmin', 't', 'b', 'pr/1', 'main')
    with pytest.raises(ValueError):
        client.mark_manually_merged('org', 'repo', 'testadmin', 1, 'a' * 40)


# ---- 9: the cursor never passes a pending PR

def test_advance_cursor_never_passes_merged_at_of_a_pending_pr():
    pulls = [
        {'number': 1, 'updated_at': '2026-03-05T00:00:00Z', 'merged_at': '2026-03-01T00:00:00Z'},
        {'number': 2, 'updated_at': '2026-03-02T00:00:00Z', 'merged_at': '2026-03-02T00:00:00Z'},
        {'number': 3, 'updated_at': '2026-03-03T00:00:00Z', 'merged_at': '2026-03-03T00:00:00Z'},
    ]
    st = MirrorState(cursor=CURSOR)
    sync.advance_cursor(st, pulls, {2, 3})  # 1 pending: merged first, updated last
    assert st.cursor <= datetime(2026, 3, 1, tzinfo=timezone.utc)  # not past PR 1's merged_at
    sync.advance_cursor(st, pulls, {1, 2, 3})
    assert st.cursor == datetime(2026, 3, 5, tzinfo=timezone.utc)
