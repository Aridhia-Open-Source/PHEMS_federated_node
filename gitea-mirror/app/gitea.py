import hashlib
import os
import re
import secrets
import time
from urllib.parse import quote

import requests
from app.clients import UserSyncError

PAGE_SIZE = 50
TIMEOUT = 30

SHADOW_PREFIX = 'gh-'
SHADOW_DOMAIN = 'shadow.invalid'
MAX_USERNAME = 40
_SEGMENT = re.compile(r'[A-Za-z0-9_.-]+')


def shadow_login(github_login: str) -> str:
    """
    The Gitea username that stands for a GitHub login. Always prefixed `gh-`, so it can never be
    the admin or an organization. Gitea allows [A-Za-z0-9_.-] without two special characters in a
    row (GitHub bots are named like 'dependabot[bot]'). A login that needs changing gets
    `.<hash of the original>` appended; GitHub logins cannot contain '.', so 'foo[bot]' and
    'foo-bot' stay distinct users.
    """
    clean = re.sub(r'[^A-Za-z0-9_.-]+', '-', github_login).strip('-.')
    plain = (
        clean == github_login and clean and not re.search(r'[-_.]{2}', clean)
        and not clean.lower().endswith(('.git', '.atom'))
        and len(SHADOW_PREFIX) + len(clean) <= MAX_USERNAME
    )
    if plain:
        return SHADOW_PREFIX + clean
    digest = hashlib.sha256(github_login.encode()).hexdigest()[:8]
    room = MAX_USERNAME - len(SHADOW_PREFIX) - 1 - len(digest)
    stem = re.sub(r'[-_.]{2,}', '-', clean)[:room].strip('-._') or 'user'
    return f'{SHADOW_PREFIX}{stem}.{digest}'


def segment(value: str, what: str = 'name') -> str:
    """A value that goes into a URL path: Gitea's character set, never '.' or '..', quoted."""
    if not isinstance(value, str) or not _SEGMENT.fullmatch(value) or value in ('.', '..'):
        raise ValueError(f'Invalid {what} for a Gitea path: {value!r}')
    return quote(value, safe='')


class GiteaError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f'Gitea returned {status}: {message}')
        self.status = status
        self.message = message


class MergeCommitNotInBaseError(GiteaError):
    """manually-merged needs the merge commit to already be in the Gitea base branch."""


class HttpGiteaClient:
    """Admin-token Gitea REST client. Git push and fetch are not done here."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.api = self.base_url + '/api/v1'
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'token {token}'

    @classmethod
    def from_env(cls) -> 'HttpGiteaClient':
        return cls(os.environ['GITEA_MIRROR_GITEA_URL'], os.environ['GITEA_MIRROR_GITEA_TOKEN'])

    def git_remote(self, org: str, repo: str) -> tuple[str, str]:
        """The repository's git URL and the Authorization header value for git push."""
        path = f'{segment(org, "organization")}/{segment(repo, "repository")}'
        return f'{self.base_url}/{path}.git', self.session.headers['Authorization']

    def _request(self, method: str, path: str, expected: tuple, sudo: str = None, **kwargs):
        headers = {}
        if sudo:
            # Never act as the admin or any real account, only as a shadow user.
            if not sudo.startswith(SHADOW_PREFIX):
                raise ValueError(f'Refusing to Sudo as {sudo!r}: not a shadow user')
            headers['Sudo'] = segment(sudo, 'user')
        response = self.session.request(
            method, f'{self.api}{path}', headers=headers, timeout=TIMEOUT, **kwargs
        )
        if response.status_code not in expected:
            message = response.json()['message'] if response.content else response.reason
            raise GiteaError(response.status_code, message)
        return response

    @staticmethod
    def _repo_path(org: str, repo: str) -> str:
        return f'/repos/{segment(org, "organization")}/{segment(repo, "repository")}'

    def _exists(self, path: str) -> bool:
        return self._request('GET', path, (200, 404)).status_code == 200

    def ensure_user(self, github_login: str) -> bool:
        """Create the shadow user for a GitHub login if missing. True if created. An existing
        account of that name that is not a shadow user (no @shadow.invalid email: the admin, an
        organization, a person) is an error: it is never adopted."""
        login = shadow_login(github_login)
        try:
            response = self._request('GET', f'/users/{segment(login, "user")}', (200, 404))
            if response.status_code == 200:
                if not str(response.json().get('email') or '').endswith('@' + SHADOW_DOMAIN):
                    raise UserSyncError(
                        f'Gitea account {login} exists but is not a shadow user; not using it')
                return False
            self._request('POST', '/admin/users', (201,), json={
                'username': login,
                'email': f'{login}@{SHADOW_DOMAIN}',
                'password': secrets.token_urlsafe(24) + 'Aa1',
                'must_change_password': False,
                'visibility': 'private',
            })
        except GiteaError as exc:
            raise UserSyncError(str(exc)) from exc
        return True

    def ensure_org(self, org: str) -> bool:
        """Create a private organization if missing. True if created."""
        if self._exists(f'/orgs/{segment(org, "organization")}'):
            return False
        self._request('POST', '/orgs', (201,), json={'username': org, 'visibility': 'private'})
        return True

    def ensure_repo(self, org: str, repo: str, default_branch: str) -> bool:
        """Create a normal (not pull mirror) private repository with manual merge allowed.
        True if created."""
        path = f'/repos/{segment(org, "organization")}/{segment(repo, "repository")}'
        created = not self._exists(path)
        if created:
            self._request('POST', f'/orgs/{segment(org, "organization")}/repos', (201,), json={
                'name': repo, 'auto_init': False, 'private': True, 'default_branch': default_branch,
            })
        self._request('PATCH', path, (200,), json={'allow_manual_merge': True})
        return created

    def add_collaborator(self, org: str, repo: str, login: str) -> None:
        """Give the shadow user write access, needed to open PRs with Sudo on a private repo."""
        self._request(
            'PUT', f'{self._repo_path(org, repo)}/collaborators/{segment(login, "user")}', (204,), json={'permission': 'write'}
        )

    def find_pull_request(self, org: str, repo: str, head: str) -> dict | None:
        """The Gitea PR (any state) whose head branch is `head`, or None. Gitea accepts
        duplicate PRs for one head, so callers look before they open."""
        page = 1
        while True:
            items = self._request(
                'GET', f'{self._repo_path(org, repo)}/pulls', (200,),
                params={'state': 'all', 'page': page, 'limit': PAGE_SIZE},
            ).json()
            for item in items:
                if item['head']['ref'] == head:
                    return item
            if len(items) < PAGE_SIZE:
                return None
            page += 1

    def get_pull_request(self, org: str, repo: str, index: int) -> dict:
        return self._request('GET', f'{self._repo_path(org, repo)}/pulls/{int(index)}', (200,)).json()

    def wait_for_pull_request_base(self, org: str, repo: str, index: int, timeout: float = 20) -> bool:
        """
        Gitea recomputes an open PR's merge base asynchronously after its base branch moves.
        Wait until it is not the PR head itself (which is what it becomes once the base has
        reached the merge commit, giving an empty diff). True if that happened in time.
        """
        deadline = time.monotonic() + timeout
        while True:
            pull = self.get_pull_request(org, repo, index)
            if pull.get('merge_base') and pull['merge_base'] != pull['head']['sha']:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.25)

    def open_pull_request(
        self, org: str, repo: str, login: str, title: str, body: str, head: str, base: str
    ) -> int:
        """Open a PR as the shadow user. Returns the Gitea PR index."""
        response = self._request(
            'POST', f'{self._repo_path(org, repo)}/pulls', (201,), sudo=login,
            json={'title': title, 'body': body, 'head': head, 'base': base},
        )
        return response.json()['number']

    def mark_manually_merged(self, org: str, repo: str, login: str, index: int, merge_sha: str) -> None:
        try:
            self._request(
                'POST', f'{self._repo_path(org, repo)}/pulls/{int(index)}/merge', (200,), sudo=login,
                json={'Do': 'manually-merged', 'MergeCommitID': merge_sha},
            )
        except GiteaError as exc:
            if exc.status == 400 and exc.message.startswith('commit not found in base'):
                raise MergeCommitNotInBaseError(exc.status, exc.message) from exc
            raise

    def get_pull_request_files(self, org: str, repo: str, index: int) -> list[dict]:
        files = []
        page = 1
        while True:
            items = self._request(
                'GET', f'{self._repo_path(org, repo)}/pulls/{int(index)}/files', (200,),
                params={'page': page, 'limit': PAGE_SIZE},
            ).json()
            if not items:
                return files
            files.extend(items)
            page += 1
