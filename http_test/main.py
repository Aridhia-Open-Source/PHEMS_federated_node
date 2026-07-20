#!/usr/bin/env python

"""
Minimal example: Backend API with automatic token refresh via OAuthAdapter.

Architecture:
- BaseHttpAdapter: base adapter with default retry logic
- OAuthAdapter: extends BaseHttpAdapter, auto-refreshes on 401/403
- BaseSession: base session with base URL support, mounts BaseHttpAdapter by default
- BackendSession: extends BaseSession, handles login + token refresh, mounts OAuthAdapter
- BackendAPI: pure client code, delegates to session
"""

import logging
import time
import subprocess
import base64

from urllib3.util import Retry
import requests
from requests import Session
from requests.adapters import HTTPAdapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaseHttpAdapter(HTTPAdapter):
    """Base HTTP adapter with default retry logic."""

    retry_limit = 3
    backoff_factor = 0.5
    default_timeout = 10
    retry_status_forcelist = {429}

    def __init__(
        self,
        base_url: str = '',
        timeout: int | None = None,
        max_retries: Retry | None = None,
        **kwargs
    ):
        self.base_url = base_url
        self.timeout = timeout or self.default_timeout
        super().__init__(**{**kwargs, 'max_retries': max_retries})

    @property
    def default_retry(self):
        return Retry(
            total=self.retry_limit,
            backoff_factor=self.backoff_factor,
            status_forcelist=self.retry_status_forcelist
        )

    def send(self, request, **kwargs):
        kwargs["timeout"] = kwargs.pop("timeout", self.timeout)
        return super().send(request, **kwargs)


class BaseSession(Session):
    """Base session with base URL support."""

    @property
    def base_url(self) -> str:
        return self.adapter.base_url

    def __init__(
        self,
        adapter: BaseHttpAdapter,
        *args,
        default_raise_for_status: bool = False,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.mount_adapters(adapter)
        self.default_raise_for_status = default_raise_for_status

    def request(self, method, url, raise_for_status: bool | None = None, **kwargs):
        full_url = f"{self.base_url}/{url.lstrip('/')}"
        response = super().request(method, full_url, **kwargs)
        return self.handle_response(response, raise_for_status)

    def handle_response(self, response, raise_for_status: bool | None = None):
        if raise_for_status is None:
            raise_for_status = self.default_raise_for_status
        if raise_for_status:
            response.raise_for_status()
        return response

    def mount_adapters(self, adapter):
        self.adapter = adapter
        self.mount("http://", self.adapter)
        self.mount("https://", self.adapter)


class OAuthAdapter(BaseHttpAdapter):
    """HTTP adapter that handles login and automatic token refresh on 401/403."""

    oauth_status_codes = {401, 403}
    oauth_backoff_factor = 0.5
    oauth_retry_limit = 3

    def __init__(self, base_url: str, username: str, password: str):
        super().__init__(base_url=base_url)
        self.username = username
        self.password = password
        self._access_token = None

    @property
    def access_token(self):
        if not self._access_token:
            self.refresh_tokens()
        return self._access_token

    @access_token.setter
    def access_token(self, value):
        self._access_token = value

    def refresh_tokens(self):
        """Refresh tokens"""
        raise NotImplementedError

    def send(self, request, **kwargs):
        if self.access_token:
            request.headers["Authorization"] = f"Bearer {self.access_token}"

        timeout = kwargs.pop("timeout", self.timeout)
        response = super().send(request, timeout=timeout, **kwargs)
        if response.status_code not in self.oauth_status_codes:
            return response

        return self._retry_on_auth_failure(request, response, timeout, **kwargs)

    def _send_request(self, request, **kwargs):
        """Send request without OAuth refresh logic."""
        kwargs['timeout'] = kwargs.get("timeout", self.timeout)
        return super().send(request, **kwargs)

    def _retry_on_auth_failure(self, request, response, timeout, **kwargs):
        for attempt in range(1, self.oauth_retry_limit + 1):
            backoff = self.oauth_backoff_factor * (2 ** (attempt - 1))
            self._log_refresh_error(response, attempt, backoff)
            time.sleep(backoff)
            self.refresh_tokens()

            response = super().send(request, timeout=timeout, **kwargs)
            if response.status_code not in self.oauth_status_codes:
                return response

        return response

    def _log_refresh_error(self, response, attempt, backoff):
        tpl = "Auth failure (%d), refresh token retry %d/%d in %.1fs"
        logger.error(tpl, response.status_code, attempt, self.oauth_retry_limit, backoff)


class BackendAdapter(OAuthAdapter):
    def login(self):
        """Exchange username/password for token."""
        logger.info(f"Logging in as {self.username}")

        req = requests.Request(
            method="POST",
            url=f"{self.base_url}/login",
            data={"username": self.username, "password": self.password},
        ).prepare()

        response = self._send_request(req, timeout=self.timeout)
        response.raise_for_status()
        return response

    def refresh_tokens(self):
        """Refresh token by logging in again."""
        logger.warning(f"Refreshing token for {self.username}")
        self.access_token = self.login().json()['token']


class BackendSession(BaseSession):
    """Backend session with automatic token refresh via OAuthAdapter."""


class BackendAPI:
    """Backend API client. All requests auto-refresh tokens on 401/403."""

    def __init__(self, session: BackendSession):
        self.session = session

    def get_repositories(self) -> list:
        """Get all repositories."""
        logger.info("Fetching repositories")
        response = self.session.get("/repositories")
        return response.json()

    def get_repository(self, repo_id: int) -> dict:
        """Get single repository."""
        logger.info(f"Fetching repository {repo_id}")
        response = self.session.get(f"/repositories/{repo_id}")
        return response.json()


def _load_creds():
    """Load credentials from K8s secret."""
    user = _get_k8s_secret("dagster-keycloak-creds", "keycloak", "DAGSTER_KC_USER")
    password = _get_k8s_secret("dagster-keycloak-creds", "keycloak", "DAGSTER_KC_PASSWORD")
    if not user or not password:
        raise ValueError("Could not load credentials from K8s")
    return {'username': user, 'password': password}


def _get_k8s_secret(secret_name: str, namespace: str, key: str) -> str:
    """Fetch a secret value from Kubernetes."""
    result = subprocess.run(
        ["kubectl", "get", "secret", secret_name, f"-n{namespace}",
            "-o", f"jsonpath={{.data.{key}}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return base64.b64decode(result.stdout).decode()


def main():
    backend_url = "http://localhost:5000"

    # Fetch credentials from K8s
    creds = _load_creds()
    logger.info(f"login - {creds}")

    # Initialize backend session, adapter, and API client
    adapter = BackendAdapter(
        base_url=backend_url,
        username=creds['username'],
        password=creds['password'],
    )
    session = BackendSession(adapter)
    api = BackendAPI(session)

    # Fetch repositories
    repos = api.get_repositories()
    logger.info(f"Found {len(repos)} repositories")
    for repo in repos:
        logger.info(f"  - {repo.get('uri')} (id={repo.get('id')})")


if __name__ == "__main__":
    main()
