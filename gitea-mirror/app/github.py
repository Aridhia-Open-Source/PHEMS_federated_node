import base64
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.clients import UserSyncError

GH_API_BASE_URL = 'https://api.github.com'
GH_PAGE_SIZE = 100
TIMEOUT = 30

K8S_API = 'https://kubernetes.default.svc'
K8S_SA_DIR = '/var/run/secrets/kubernetes.io/serviceaccount'
SECRET_DATA_FIELD = 'token'


class GithubError(UserSyncError):
    """A GitHub call failed."""


class TokenExpired(GithubError):
    """GitHub rejected the token (401). The message carries token_expired for the status flag."""

    def __init__(self, url: str):
        super().__init__(f'token_expired: GitHub rejected the token for {url}')


class RateLimited(GithubError):
    def __init__(self, url: str, reset_at: datetime):
        super().__init__(f'GitHub rate limit hit for {url}; resets at {reset_at.isoformat()}')
        self.reset_at = reset_at


def read_secret_token(namespace: str, key: str) -> str:
    """
    Read the GitHub token from the Kubernetes secret named `key` in `namespace`, field
    `token`, with the pod's service account. Tests replace this function.
    """
    with open(f'{K8S_SA_DIR}/token') as f:
        sa_token = f.read().strip()
    response = requests.get(
        f'{K8S_API}/api/v1/namespaces/{namespace}/secrets/{key}',
        headers={'Authorization': f'Bearer {sa_token}'},
        verify=f'{K8S_SA_DIR}/ca.crt',
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return base64.b64decode(response.json()['data'][SECRET_DATA_FIELD]).decode().strip()


def repo_path(upstream_uri: str) -> str:
    """owner/name from https://github.com/owner/name(.git)."""
    path = urlparse(upstream_uri).path.strip('/')
    path = path.removesuffix('.git')
    if path.count('/') != 1:
        raise GithubError(f'Cannot read owner/repo from upstream uri {upstream_uri}')
    return path


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class GithubRestClient:
    def __init__(self, base_uri: str = GH_API_BASE_URL, session: requests.Session = None):
        self._base_uri = base_uri.rstrip('/')
        self._session = session or requests.Session()
        # Retry transient server errors only; 403/429 are surfaced, never slept on.
        retry = Retry(total=3, backoff_factor=1, status_forcelist=(500, 502, 503, 504))
        self._session.mount('https://', HTTPAdapter(max_retries=retry))
        self._session.headers.update({
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        })
        # url (with params) -> (etag, items, next_url)
        self._etags: dict[str, tuple[str, list, str | None]] = {}

    def _get_page(self, url: str, token: str, params: dict | None = None):
        """One page: (items, next_url). Sends If-None-Match and reuses the cached page on 304."""
        cache_key = requests.Request('GET', url, params=params).prepare().url
        headers = {'Authorization': f'Bearer {token}'}
        if cache_key in self._etags:
            headers['If-None-Match'] = self._etags[cache_key][0]
        response = self._session.get(url, params=params, headers=headers, timeout=TIMEOUT)

        if response.status_code == 304:
            _, items, next_url = self._etags[cache_key]
            return items, next_url
        if response.status_code == 401:
            raise TokenExpired(url)
        if response.status_code in (403, 429):
            self._raise_if_rate_limited(url, response)
        response.raise_for_status()

        items = response.json()
        next_url = response.links.get('next', {}).get('url')
        if 'ETag' in response.headers:
            self._etags[cache_key] = (response.headers['ETag'], items, next_url)
        return items, next_url

    @staticmethod
    def _raise_if_rate_limited(url: str, response: requests.Response):
        headers = response.headers
        if headers.get('X-RateLimit-Remaining') == '0' and 'X-RateLimit-Reset' in headers:
            reset_at = datetime.fromtimestamp(int(headers['X-RateLimit-Reset']), tz=timezone.utc)
            raise RateLimited(url, reset_at)
        if 'Retry-After' in headers:
            reset_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + int(headers['Retry-After']), tz=timezone.utc
            )
            raise RateLimited(url, reset_at)

    def _pages(self, path: str, token: str, params: dict):
        """Yield pages of items, following the Link header."""
        url, page_params = f'{self._base_uri}/{path}', {**params, 'per_page': GH_PAGE_SIZE}
        while url:
            items, url = self._get_page(url, token, page_params)
            page_params = None  # the next url already carries the query
            yield items

    def _logins(self, path: str, token: str) -> list[str]:
        return [u['login'] for page in self._pages(path, token, {}) for u in page]

    def list_users(self, upstream_uri: str, secret_namespace: str, secret_key: str) -> list[str]:
        """
        Contributors and collaborators, de-duplicated. The collaborators endpoint needs push
        access to the repository; a 403 there means the token is read-only, so we use
        contributors alone. (A rate-limit 403 still raises.)
        """
        token = read_secret_token(secret_namespace, secret_key)
        repo = repo_path(upstream_uri)
        logins = self._logins(f'repos/{repo}/contributors', token)
        try:
            logins += self._logins(f'repos/{repo}/collaborators', token)
        except requests.HTTPError as err:
            if err.response.status_code != 403:
                raise
        return sorted(set(logins))

    def list_merged_pulls(
        self, upstream_uri: str, secret_namespace: str, secret_key: str, base_branch: str, cursor: str
    ) -> list[dict]:
        """
        PRs merged into base_branch and updated after `cursor` (an updated_at timestamp),
        oldest first. Lists closed PRs most recently updated first and stops at the cursor
        (the search API is rate limited harder and lags).
        """
        token = read_secret_token(secret_namespace, secret_key)
        cursor_dt = _parse_ts(cursor)
        params = {'state': 'closed', 'base': base_branch, 'sort': 'updated', 'direction': 'desc'}
        merged = []
        for page in self._pages(f'repos/{repo_path(upstream_uri)}/pulls', token, params):
            for pr in page:
                # updated_at is never before merged_at, so nothing older is newly merged
                if _parse_ts(pr['updated_at']) <= cursor_dt:
                    return merged[::-1]
                if pr['merged_at']:
                    merged.append({
                        'number': pr['number'],
                        'title': pr['title'],
                        'author': pr['user']['login'],
                        'merged_at': pr['merged_at'],
                        'updated_at': pr['updated_at'],
                        'merge_commit_sha': pr['merge_commit_sha'],
                        'head_sha': pr['head']['sha'],
                    })
        return merged[::-1]
