import os
import secrets
import requests
from app.clients import UserSyncError

PAGE_SIZE = 50
TIMEOUT = 30


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
        self.api = base_url.rstrip('/') + '/api/v1'
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'token {token}'

    @classmethod
    def from_env(cls) -> 'HttpGiteaClient':
        return cls(os.environ['GITEA_MIRROR_GITEA_URL'], os.environ['GITEA_MIRROR_GITEA_TOKEN'])

    def _request(self, method: str, path: str, expected: tuple, sudo: str = None, **kwargs):
        headers = {'Sudo': sudo} if sudo else {}
        response = self.session.request(
            method, f'{self.api}{path}', headers=headers, timeout=TIMEOUT, **kwargs
        )
        if response.status_code not in expected:
            message = response.json()['message'] if response.content else response.reason
            raise GiteaError(response.status_code, message)
        return response

    def _exists(self, path: str) -> bool:
        return self._request('GET', path, (200, 404)).status_code == 200

    def ensure_user(self, login: str) -> bool:
        try:
            if self._exists(f'/users/{login}'):
                return False
            self._request('POST', '/admin/users', (201,), json={
                'username': login,
                'email': f'{login}@shadow.invalid',
                'password': secrets.token_urlsafe(24) + 'Aa1',
                'must_change_password': False,
                'visibility': 'private',
            })
        except GiteaError as exc:
            raise UserSyncError(str(exc)) from exc
        return True

    def ensure_org(self, org: str) -> bool:
        """Create a private organization if missing. True if created."""
        if self._exists(f'/orgs/{org}'):
            return False
        self._request('POST', '/orgs', (201,), json={'username': org, 'visibility': 'private'})
        return True

    def ensure_repo(self, org: str, repo: str, default_branch: str) -> bool:
        """Create a normal (not pull mirror) private repository with manual merge allowed.
        True if created."""
        path = f'/repos/{org}/{repo}'
        created = not self._exists(path)
        if created:
            self._request('POST', f'/orgs/{org}/repos', (201,), json={
                'name': repo, 'auto_init': False, 'private': True, 'default_branch': default_branch,
            })
        self._request('PATCH', path, (200,), json={'allow_manual_merge': True})
        return created

    def add_collaborator(self, org: str, repo: str, login: str) -> None:
        """Give the shadow user write access, needed to open PRs with Sudo on a private repo."""
        self._request(
            'PUT', f'/repos/{org}/{repo}/collaborators/{login}', (204,), json={'permission': 'write'}
        )

    def open_pull_request(
        self, org: str, repo: str, login: str, title: str, body: str, head: str, base: str
    ) -> int:
        """Open a PR as the shadow user. Returns the Gitea PR index."""
        response = self._request(
            'POST', f'/repos/{org}/{repo}/pulls', (201,), sudo=login,
            json={'title': title, 'body': body, 'head': head, 'base': base},
        )
        return response.json()['number']

    def mark_manually_merged(self, org: str, repo: str, login: str, index: int, merge_sha: str) -> None:
        try:
            self._request(
                'POST', f'/repos/{org}/{repo}/pulls/{index}/merge', (200,), sudo=login,
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
                'GET', f'/repos/{org}/{repo}/pulls/{index}/files', (200,),
                params={'page': page, 'limit': PAGE_SIZE},
            ).json()
            if not items:
                return files
            files.extend(items)
            page += 1
