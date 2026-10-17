"""
Review findings 2, 6, 7, 9, 10 against a real Gitea: no duplicate PRs after a transient failure,
the base branch is never left rewound, poison PRs are quarantined, shadow users never alias real
accounts, ADR "no backfill", and upstream branches that collide with pr/<n>.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import responses
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    'GITEA_MIRROR_GITEA_URL' not in os.environ, reason='needs a real Gitea: run run_gitea_tests.sh'
)

from app import create_app, github, sync  # noqa: E402
from app.clients import UserSyncError  # noqa: E402
from app.gitea import GiteaError, HttpGiteaClient, shadow_login  # noqa: E402
from app.github import GithubRestClient  # noqa: E402
from app.helpers.base_model import db  # noqa: E402
from app.models.mirror import Mirror, MirrorState, MirroredPullRequest  # noqa: E402
from tests.test_sync_gitea import git, upstream  # noqa: E402,F401

CURSOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setattr(github, 'read_secret_token', lambda ns, key: 'ghp_test')


def pulls(merges, overrides=None):
    """GitHub closed-PR list for the upstream fixture; overrides: {n: {field: value}}."""
    meta = {
        1: ('alice', '2026-03-01T00:00:00Z'),
        2: ('dependabot[bot]', '2026-03-02T00:00:00Z'),
        3: ('bob', '2026-03-03T00:00:00Z'),
    }
    items = []
    for n in (3, 2, 1):
        item = {
            'number': n, 'title': f'PR {n}', 'user': {'login': meta[n][0]},
            'merged_at': meta[n][1], 'updated_at': meta[n][1],
            'merge_commit_sha': merges[n], 'head': {'sha': f'h{n}'},
        }
        item.update((overrides or {}).get(n, {}))
        items.append(item)
    return sorted(items, key=lambda p: p['updated_at'], reverse=True)


class Env:
    def __init__(self, tmp_path, gitea_cls=HttpGiteaClient):
        self.gitea = gitea_cls.from_env()
        self.org = f'org-{uuid.uuid4().hex[:8]}'
        self.app = create_app(github_client=GithubRestClient(), gitea_client=self.gitea,
                              git_cache=sync.GitCache(str(tmp_path / 'cache')))
        self.app.testing = True

    def add_mirror(self, name, base='main'):
        mirror = Mirror(
            upstream_uri=f'https://github.com/{name}', secret_namespace='ns', secret_key='key',
            gitea_owner=self.org, gitea_repo='mirror', base_branch=base, enabled=True,
        )
        db.session.add(mirror)
        db.session.flush()
        self.mid = mirror.id
        db.session.add(MirrorState(mirror_id=self.mid, cursor=CURSOR))
        db.session.commit()

    def resync(self):
        return sync.resync(self.mid, self.app.extensions['github_client'], self.gitea,
                           self.app.extensions['git_cache'])

    def rows(self):
        db.session.expire_all()
        return {r.number: r for r in db.session.scalars(
            select(MirroredPullRequest).where(MirroredPullRequest.mirror_id == self.mid))}

    def state(self):
        db.session.expire_all()
        return db.session.get(MirrorState, self.mid)

    def gitea_pulls(self):
        return self.gitea._request('GET', f'/repos/{self.org}/mirror/pulls', (200,),
                                   params={'state': 'all', 'limit': 50}).json()

    def main_sha(self, branch='main'):
        return self.gitea._request(
            'GET', f'/repos/{self.org}/mirror/branches/{branch}', (200,)).json()['commit']['id']


@pytest.fixture
def env(migrated, tmp_path):
    with create_app(github_client=GithubRestClient(), gitea_client=HttpGiteaClient.from_env(),
                    git_cache=sync.GitCache(str(tmp_path))).app_context():
        yield Env(tmp_path)


# ---- 2: duplicate Gitea PRs

class FlakyMerge(HttpGiteaClient):
    failures = 1

    def mark_manually_merged(self, *args, **kwargs):
        if FlakyMerge.failures:
            FlakyMerge.failures -= 1
            raise GiteaError(500, 'transient')
        return super().mark_manually_merged(*args, **kwargs)


class FlakyOpen(HttpGiteaClient):
    """Opens the PR in Gitea, then loses the response (timeout after the request went through)."""
    failures = 1

    def open_pull_request(self, *args, **kwargs):
        index = super().open_pull_request(*args, **kwargs)
        if FlakyOpen.failures:
            FlakyOpen.failures -= 1
            raise GiteaError(504, 'gateway timeout')
        return index


@pytest.mark.parametrize('cls', [FlakyMerge, FlakyOpen])
@responses.activate
def test_transient_failure_after_open_does_not_duplicate_pr(migrated, upstream, tmp_path, cls):
    cls.failures = 1
    name, merges, tip = upstream
    responses.add_passthru(os.environ['GITEA_MIRROR_GITEA_URL'])
    responses.get(f'https://api.github.com/repos/{name}/pulls', json=pulls(merges))
    e = Env(tmp_path, cls)
    with e.app.app_context():
        e.add_mirror(name)
        with pytest.raises(GiteaError):
            e.resync()
        assert e.rows() == {}  # nothing recorded yet, but Gitea has an open PR for pr/1
        assert e.main_sha() == tip  # and the base is not left rewound
        assert 'Gitea returned' in e.state().last_error

        assert e.resync() == [1, 2, 3]
        heads = [p['head']['ref'] for p in e.gitea_pulls()]
        assert sorted(heads) == ['pr/1', 'pr/2', 'pr/3']  # exactly one per GitHub PR
        assert all(p['merged'] for p in e.gitea_pulls())
        rows = e.rows()
        assert {n: r.gitea_pr_number for n, r in rows.items()} == {1: 1, 2: 2, 3: 3}
        files = e.gitea.get_pull_request_files(e.org, 'mirror', rows[1].gitea_pr_number)
        assert [f['filename'] for f in files] == ['a.txt']
        assert e.main_sha() == tip


# ---- 6: base branch rewound / poison PR

class AlwaysFailMerge(HttpGiteaClient):
    def mark_manually_merged(self, org, repo, login, index, merge_sha):
        if index == 2:
            raise GiteaError(500, 'down')
        return super().mark_manually_merged(org, repo, login, index, merge_sha)


@responses.activate
def test_failure_mid_replay_restores_base_to_tip(migrated, upstream, tmp_path):
    name, merges, tip = upstream
    responses.add_passthru(os.environ['GITEA_MIRROR_GITEA_URL'])
    responses.get(f'https://api.github.com/repos/{name}/pulls', json=pulls(merges))
    e = Env(tmp_path, AlwaysFailMerge)
    with e.app.app_context():
        e.add_mirror(name)
        with pytest.raises(GiteaError):
            e.resync()
        assert sorted(e.rows()) == [1]  # PR 1 done, PR 2 failed
        assert e.main_sha() == tip  # not left at PR 2's parent or merge commit


@responses.activate
def test_poison_prs_are_quarantined_and_do_not_block_later_prs(env, upstream):
    name, merges, tip = upstream
    responses.add_passthru(os.environ['GITEA_MIRROR_GITEA_URL'])
    responses.get(f'https://api.github.com/repos/{name}/pulls', json=pulls(
        merges, {1: {'merge_commit_sha': None}, 2: {'merge_commit_sha': 'f' * 40}}))
    env.add_mirror(name)

    with pytest.raises(sync.PullRequestsFailed) as err:
        env.resync()
    assert '#1' in str(err.value) and '#2' in str(err.value)
    assert sorted(env.rows()) == [3]  # the healthy PR got through
    assert env.main_sha() == tip  # base is at the upstream tip, not rewound
    last = env.state().last_error
    assert '#1' in last and '#2' in last
    assert [p['head']['ref'] for p in env.gitea_pulls()] == ['pr/3']  # nothing half-open

    # Each tick retries the poison PRs without opening anything or moving the base.
    with pytest.raises(sync.PullRequestsFailed):
        env.resync()
    assert env.main_sha() == tip and len(env.gitea_pulls()) == 1


# ---- 7: shadow users

def test_shadow_user_never_aliases_a_real_account(env):
    gitea = env.gitea
    admin = gitea._request('GET', '/user', (200,)).json()['login']
    gitea.ensure_user(admin)  # creates (or finds) gh-<admin>; never adopts the admin
    shadow = gitea._request('GET', f'/users/{shadow_login(admin)}', (200,)).json()
    assert shadow['login'] == shadow_login(admin) != admin
    assert shadow['email'].endswith('@shadow.invalid')


def test_existing_non_shadow_account_with_shadow_name_is_refused(env):
    name = 'real' + uuid.uuid4().hex[:6]
    env.gitea._request('POST', '/admin/users', (201,), json={
        'username': shadow_login(name), 'email': f'{name}@example.com',
        'password': 'Aa1-' + uuid.uuid4().hex, 'must_change_password': False})
    with pytest.raises(UserSyncError, match='not a shadow user'):
        env.gitea.ensure_user(name)


def test_org_named_like_shadow_user_is_refused(env):
    name = 'org' + uuid.uuid4().hex[:6]
    env.gitea.ensure_org(shadow_login(name))
    with pytest.raises(UserSyncError, match='not a shadow user'):
        env.gitea.ensure_user(name)


def test_bot_and_hyphen_logins_become_distinct_users(env):
    base = 'foo' + uuid.uuid4().hex[:6]
    assert env.gitea.ensure_user(f'{base}[bot]') is True
    assert env.gitea.ensure_user(f'{base}-bot') is True
    assert env.gitea.ensure_user(f'{base}[bot]') is False


def test_login_that_sanitises_to_empty_gets_a_valid_user(env):
    assert env.gitea.ensure_user('[bot]') in (True, False)
    assert env.gitea._request('GET', f'/users/{shadow_login("[bot]")}', (200,))


@responses.activate
def test_pr_by_admin_named_author_is_opened_as_shadow(env, upstream):
    name, merges, tip = upstream
    responses.add_passthru(os.environ['GITEA_MIRROR_GITEA_URL'])
    admin = env.gitea._request('GET', '/user', (200,)).json()['login']
    responses.get(f'https://api.github.com/repos/{name}/pulls', json=pulls(
        merges, {1: {'user': {'login': admin}}}))
    env.add_mirror(name)
    env.resync()
    index = env.rows()[1].gitea_pr_number
    pull = env.gitea._request('GET', f'/repos/{env.org}/mirror/pulls/{index}', (200,)).json()
    assert pull['user']['login'] == shadow_login(admin) != admin


# ---- 9: no backfill

@responses.activate
def test_pr_merged_before_mirror_creation_but_updated_later_is_not_replayed(env, upstream):
    name, merges, tip = upstream
    responses.add_passthru(os.environ['GITEA_MIRROR_GITEA_URL'])
    # PR 1 merged in 2025 (before the cursor), commented on in March
    responses.get(f'https://api.github.com/repos/{name}/pulls', json=pulls(
        merges, {1: {'merged_at': '2025-12-01T00:00:00Z', 'updated_at': '2026-03-05T00:00:00Z'}}))
    env.add_mirror(name)
    assert env.resync() == [2, 3]
    assert sorted(env.rows()) == [2, 3]
    assert env.main_sha() == tip
    # the cursor still moves past it, so it is not listed as pending forever
    assert env.state().cursor == datetime(2026, 3, 5, tzinfo=timezone.utc)
    assert env.resync() == []


@responses.activate
def test_pending_pr_merged_earlier_than_done_ones_is_not_mistaken_for_history(env, upstream):
    """PR 1 merged first but was updated last (PR 2 and 3 finish first). If PR 1 fails once, the
    cursor must not pass its merged_at, or the retry would treat it as pre-mirror history."""
    name, merges, tip = upstream
    responses.add_passthru(os.environ['GITEA_MIRROR_GITEA_URL'])
    url = f'https://api.github.com/repos/{name}/pulls'
    late = {1: {'updated_at': '2026-03-05T00:00:00Z'}}
    responses.get(url, json=pulls(merges, {**late, 1: {**late[1], 'merge_commit_sha': None}}))
    env.add_mirror(name)
    with pytest.raises(sync.PullRequestsFailed):
        env.resync()
    assert sorted(env.rows()) == [2, 3]
    assert env.state().cursor <= datetime(2026, 3, 1, tzinfo=timezone.utc)

    responses.replace(responses.GET, url, json=pulls(merges, late))
    assert env.resync() == [1]
    assert env.state().last_error is None
    assert env.state().cursor == datetime(2026, 3, 5, tzinfo=timezone.utc)
    assert env.main_sha() == tip


# ---- 10: upstream branches that collide with pr/<n>

@pytest.mark.parametrize('branch', ['pr', 'pr/2'])
@responses.activate
def test_upstream_branch_colliding_with_pr_refs_fails_clearly(env, upstream, tmp_path, branch):
    name, merges, tip = upstream
    bare = tmp_path / 'github' / name
    git(bare, 'branch', branch, 'develop')
    responses.add_passthru(os.environ['GITEA_MIRROR_GITEA_URL'])
    responses.get(f'https://api.github.com/repos/{name}/pulls', json=pulls(merges))
    env.add_mirror(name)
    with pytest.raises(sync.BranchCollision, match=f"'{branch}'"):
        env.resync()
    assert f"'{branch}'" in env.state().last_error
    assert env.rows() == {}
    repo = env.gitea._request('GET', f'/repos/{env.org}/mirror', (200,)).json()
    assert repo['empty'] is True  # nothing was pushed, so no pr refs were touched
