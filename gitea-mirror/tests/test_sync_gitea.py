"""
Sync engine end to end: recorded GitHub API responses, a local git repository standing in for
GitHub's git remote (via url.insteadOf), and a real Gitea (run_gitea_tests.sh).
"""
import os
import subprocess
import uuid
from datetime import datetime, timezone

import pytest
import responses
from sqlalchemy import func, select

pytestmark = pytest.mark.skipif(
    'GITEA_MIRROR_GITEA_URL' not in os.environ, reason='needs a real Gitea: run run_gitea_tests.sh'
)

from app import create_app, github, sync  # noqa: E402
from app.gitea import HttpGiteaClient, shadow_login  # noqa: E402
from app.github import GithubRestClient  # noqa: E402
from app.helpers.base_model import db  # noqa: E402
from app.models.mirror import (  # noqa: E402
    Mirror, MirrorState, MirroredPullRequest, Webhook, WebhookDelivery
)

CURSOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


def git(cwd, *args):
    return subprocess.run(
        ['git', *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(work, path, content, message):
    (work / path).write_text(content)
    git(work, 'add', path)
    git(work, 'commit', '-q', '-m', message)
    return git(work, 'rev-parse', 'HEAD')


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    """
    A bare 'GitHub' repository with three merged PRs, one per merge style, a later direct commit
    on main and a second branch. Returns (owner/name, {pr number: merge sha}, main tip).
    """
    name = f'gh-{uuid.uuid4().hex[:8]}/repo'
    bare = tmp_path / 'github' / name
    gitconfig = tmp_path / 'gitconfig'
    gitconfig.write_text(
        '[user]\n\tname = Test\n\temail = test@example.com\n'
        '[init]\n\tdefaultBranch = main\n'
        f'[url "file://{tmp_path}/github/"]\n\tinsteadOf = https://github.com/\n'
    )
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(gitconfig))
    git(tmp_path, 'init', '-q', '--bare', str(bare))
    work = tmp_path / 'work'
    git(tmp_path, 'init', '-q', str(work))

    root = commit(work, 'README.md', 'hi\n', 'init')
    # PR 1, merge commit
    git(work, 'checkout', '-q', '-b', 'f1')
    commit(work, 'a.txt', 'a\n', 'add a')
    git(work, 'checkout', '-q', 'main')
    git(work, 'merge', '-q', '--no-ff', 'f1', '-m', 'Merge pull request #1')
    m1 = git(work, 'rev-parse', 'HEAD')
    # PR 2, squash; branched before PR 1 merged, two commits
    git(work, 'checkout', '-q', '-b', 'f2', root)
    commit(work, 'b.txt', 'b\n', 'add b')
    commit(work, 'b2.txt', 'b2\n', 'add b2')
    git(work, 'checkout', '-q', 'main')
    git(work, 'merge', '-q', '--squash', 'f2')
    git(work, 'commit', '-q', '-m', 'PR 2 (#2)')
    s2 = git(work, 'rev-parse', 'HEAD')
    # PR 3, fast-forward
    git(work, 'checkout', '-q', '-b', 'f3')
    f3 = commit(work, 'c.txt', 'c\n', 'add c')
    git(work, 'checkout', '-q', 'main')
    git(work, 'merge', '-q', '--ff-only', 'f3')
    # direct commit after the last PR, and a second branch
    tip = commit(work, 'd.txt', 'd\n', 'direct')
    git(work, 'checkout', '-q', '-b', 'develop', root)
    commit(work, 'e.txt', 'e\n', 'develop')

    git(work, 'push', '-q', str(bare), 'main', 'develop',
        'f1:refs/pull/1/head', 'f2:refs/pull/2/head', 'f3:refs/pull/3/head')
    return name, {1: m1, 2: s2, 3: f3}, tip


def pulls_json(merges):
    """GitHub's closed-PR list, most recently updated first. PR 1 was updated after the others
    merged, so updated_at order (1, 3, 2) differs from merged_at order (1, 2, 3)."""
    meta = {
        1: ('alice', '2026-03-01T00:00:00Z', '2026-03-05T00:00:00Z'),
        2: ('dependabot[bot]', '2026-03-02T00:00:00Z', '2026-03-02T00:00:00Z'),
        3: ('bob', '2026-03-03T00:00:00Z', '2026-03-03T00:00:00Z'),
    }
    return [{
        'number': n, 'title': f'PR {n}', 'user': {'login': meta[n][0]},
        'merged_at': meta[n][1], 'updated_at': meta[n][2],
        'merge_commit_sha': merges[n], 'head': {'sha': f'h{n}'},
    } for n in (1, 3, 2)]


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setattr(github, 'read_secret_token', lambda ns, key: 'ghp_test')


@responses.activate
def test_sync_replays_each_merge_style_and_second_run_is_noop(migrated, auth, upstream, tmp_path):
    name, merges, tip = upstream
    gitea = HttpGiteaClient.from_env()
    responses.add_passthru(os.environ['GITEA_MIRROR_GITEA_URL'])
    responses.get(f'https://api.github.com/repos/{name}/pulls', json=pulls_json(merges))

    app = create_app(github_client=GithubRestClient(), gitea_client=gitea,
                     git_cache=sync.GitCache(str(tmp_path / 'cache')))
    app.testing = True
    org = f'org-{uuid.uuid4().hex[:8]}'
    with app.test_client() as client, app.app_context():
        mirror = Mirror(
            upstream_uri=f'https://github.com/{name}', secret_namespace='ns', secret_key='key',
            gitea_owner=org, gitea_repo='mirror', base_branch='main', enabled=True,
        )
        db.session.add(mirror)
        db.session.flush()
        mid = mirror.id
        db.session.add(MirrorState(mirror_id=mid, cursor=CURSOR))
        db.session.add(Webhook(url='http://receiver.invalid/hook', secret_namespace='ns',
                               secret_key='hmac', mirror_id=mid, enabled=True))
        db.session.commit()

        resp = client.post(f'/mirrors/{mid}/resync', headers=auth)
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()['mirrored'] == [1, 2, 3]  # merged_at order

        rows = {r.number: r for r in db.session.scalars(
            select(MirroredPullRequest).where(MirroredPullRequest.mirror_id == mid))}
        assert {n: r.gitea_pr_number for n, r in rows.items()} == {1: 1, 2: 2, 3: 3}
        assert rows[2].author == 'dependabot[bot]'
        assert rows[2].merged_at == datetime(2026, 3, 2, tzinfo=timezone.utc)
        assert db.session.get(MirrorState, mid).cursor == datetime(2026, 3, 5, tzinfo=timezone.utc)

        expected_files = {1: ['a.txt'], 2: ['b.txt', 'b2.txt'], 3: ['c.txt']}
        for number, files in expected_files.items():
            index = rows[number].gitea_pr_number
            pull = gitea._request('GET', f'/repos/{org}/mirror/pulls/{index}', (200,)).json()
            assert pull['merged'] is True
            assert pull['merge_commit_sha'] == merges[number]
            assert pull['head']['ref'] == f'pr/{number}'
            assert pull['base']['ref'] == 'main'
            assert pull['user']['login'] == shadow_login(rows[number].author)
            got = sorted(f['filename'] for f in gitea.get_pull_request_files(org, 'mirror', index))
            assert got == files, f'PR {number}'

        def gitea_state():
            pulls = gitea._request('GET', f'/repos/{org}/mirror/pulls', (200,),
                                   params={'state': 'all', 'limit': 50}).json()
            main = gitea._request('GET', f'/repos/{org}/mirror/branches/main', (200,)).json()
            return len(pulls), main['commit']['id'], count(MirroredPullRequest), \
                count(WebhookDelivery)

        first = gitea_state()
        assert first == (3, tip, 3, 3)
        gitea._request('GET', f'/repos/{org}/mirror/branches/develop', (200,))

        # Second run: the cursor stops the listing; nothing new anywhere.
        resp = client.post(f'/mirrors/{mid}/resync', headers=auth)
        assert resp.status_code == 200 and resp.get_json()['mirrored'] == []
        assert gitea_state() == first

        # Even if GitHub lists them again (cursor reset), our table skips them.
        db.session.get(MirrorState, mid).cursor = CURSOR
        db.session.commit()
        resp = client.post(f'/mirrors/{mid}/resync', headers=auth)
        assert resp.status_code == 200 and resp.get_json()['mirrored'] == []
        assert gitea_state() == first
        status = client.get(f'/mirrors/{mid}/status', headers=auth).get_json()
        assert status['last_error'] is None and status['prs_mirrored'] == 3


def count(model):
    return db.session.scalar(select(func.count()).select_from(model))
