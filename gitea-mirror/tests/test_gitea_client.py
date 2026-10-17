import os
import uuid
import pytest

pytestmark = pytest.mark.skipif(
    'GITEA_MIRROR_GITEA_URL' not in os.environ, reason='needs a real Gitea: run run_gitea_tests.sh'
)

from app.clients import UserSyncError  # noqa: E402
from app.gitea import GiteaError, HttpGiteaClient, MergeCommitNotInBaseError, shadow_login  # noqa: E402


@pytest.fixture(scope='module')
def gitea():
    return HttpGiteaClient.from_env()


@pytest.fixture
def name():
    return 't' + uuid.uuid4().hex[:10]


def _commit(client, org, repo, branch, path, content, parent_branch=None):
    """Create a commit on a branch through the contents API (no git needed). Returns its sha."""
    body = {'content': content, 'message': f'add {path}', 'branch': branch}
    if parent_branch:
        body['new_branch'] = branch
        body['branch'] = parent_branch
    res = client._request('POST', f'/repos/{org}/{repo}/contents/{path}', (201,), json=body)
    return res.json()['commit']['sha']


@pytest.fixture
def repo(gitea, name):
    """An org and repo whose 'main' branch holds one commit, plus a 'pr/7' branch with a file."""
    org = f'org-{name}'
    gitea.ensure_org(org)
    gitea.ensure_repo(org, 'mirror', 'main')
    # auto_init is off, so the first commit creates 'main'
    gitea._request('POST', f'/repos/{org}/mirror/contents/README.md', (201,), json={
        'content': 'aGk=', 'message': 'init', 'branch': 'main'})
    _commit(gitea, org, 'mirror', 'pr/7', 'change.txt', 'Y2hhbmdl', parent_branch='main')
    return org, 'mirror'


def test_ensure_user_creates_then_is_idempotent(gitea, name):
    assert gitea.ensure_user(name) is True
    assert gitea.ensure_user(name) is False
    user = gitea._request('GET', f'/users/{shadow_login(name)}', (200,)).json()
    assert user['login'] == shadow_login(name)
    assert user['email'].endswith('@shadow.invalid')


def test_ensure_user_error_is_user_sync_error(gitea, monkeypatch):
    class Reply:
        status_code, content, reason = 422, b'{}', 'Unprocessable'

        def json(self):
            return {'message': '[Username]: invalid'}

    monkeypatch.setattr(gitea.session, 'request', lambda *a, **k: Reply())
    with pytest.raises(UserSyncError, match='422'):
        gitea.ensure_user('anyone')


def test_ensure_user_accepts_any_github_login(gitea, name):
    assert gitea.ensure_user(f'{name}[bot]') is True  # 'bad name!' style input is sanitised


def test_ensure_org_idempotent(gitea, name):
    assert gitea.ensure_org(name) is True
    assert gitea.ensure_org(name) is False
    org = gitea._request('GET', f'/orgs/{name}', (200,)).json()
    assert org['visibility'] == 'private'


def test_ensure_repo_normal_private_manual_merge_idempotent(gitea, name):
    gitea.ensure_org(name)
    assert gitea.ensure_repo(name, 'r', 'main') is True
    assert gitea.ensure_repo(name, 'r', 'main') is False
    repo = gitea._request('GET', f'/repos/{name}/r', (200,)).json()
    assert repo['mirror'] is False
    assert repo['private'] is True
    assert repo['default_branch'] == 'main'
    assert repo['allow_manual_merge'] is True


def test_add_collaborator(gitea, repo, name):
    org, r = repo
    gitea.ensure_user(name)
    gitea.add_collaborator(org, r, shadow_login(name))
    perm = gitea._request('GET', f'/repos/{org}/{r}/collaborators/{shadow_login(name)}/permission', (200,)).json()
    assert perm['permission'] == 'write'


def test_open_pull_request_as_user(gitea, repo, name):
    org, r = repo
    gitea.ensure_user(name)
    gitea.add_collaborator(org, r, shadow_login(name))
    index = gitea.open_pull_request(org, r, shadow_login(name), 'A change', 'Mirrored', 'pr/7', 'main')
    assert index == 1
    pull = gitea._request('GET', f'/repos/{org}/{r}/pulls/{index}', (200,)).json()
    assert pull['user']['login'] == shadow_login(name)
    assert pull['head']['ref'] == 'pr/7'
    assert pull['base']['ref'] == 'main'


def test_open_pull_request_without_write_access_fails(gitea, repo, name):
    org, r = repo
    gitea.ensure_user(name)
    with pytest.raises(GiteaError):
        gitea.open_pull_request(org, r, shadow_login(name), 'A change', '', 'pr/7', 'main')


def test_get_pull_request_files(gitea, repo, name):
    org, r = repo
    gitea.ensure_user(name)
    gitea.add_collaborator(org, r, shadow_login(name))
    index = gitea.open_pull_request(org, r, shadow_login(name), 'A change', '', 'pr/7', 'main')
    files = gitea.get_pull_request_files(org, r, index)
    assert [f['filename'] for f in files] == ['change.txt']


def test_mark_manually_merged(gitea, repo, name):
    org, r = repo
    gitea.ensure_user(name)
    gitea.add_collaborator(org, r, shadow_login(name))
    index = gitea.open_pull_request(org, r, shadow_login(name), 'A change', '', 'pr/7', 'main')
    # the merge commit must already be in the base branch
    merge_sha = _commit(gitea, org, r, 'main', 'merged.txt', 'bQ==')
    gitea.mark_manually_merged(org, r, shadow_login(name), index, merge_sha)
    pull = gitea._request('GET', f'/repos/{org}/{r}/pulls/{index}', (200,)).json()
    assert pull['merged'] is True
    assert pull['merge_commit_sha'] == merge_sha
    assert [f['filename'] for f in gitea.get_pull_request_files(org, r, index)] == ['change.txt']


@pytest.mark.parametrize('known_to_repo', [True, False])
def test_mark_manually_merged_commit_not_in_base(gitea, repo, name, known_to_repo):
    org, r = repo
    gitea.ensure_user(name)
    gitea.add_collaborator(org, r, shadow_login(name))
    index = gitea.open_pull_request(org, r, shadow_login(name), 'A change', '', 'pr/7', 'main')
    if known_to_repo:  # on pr/7 but not in main: "not found in base branch"
        sha = gitea._request('GET', f'/repos/{org}/{r}/pulls/{index}', (200,)).json()['head']['sha']
    else:  # unknown to the repository: "not found in base repository"
        sha = 'a' * 40
    with pytest.raises(MergeCommitNotInBaseError, match='commit not found in base'):
        gitea.mark_manually_merged(org, r, shadow_login(name), index, sha)


def test_from_env_fails_fast(monkeypatch):
    monkeypatch.delenv('GITEA_MIRROR_GITEA_TOKEN')
    with pytest.raises(KeyError):
        HttpGiteaClient.from_env()
