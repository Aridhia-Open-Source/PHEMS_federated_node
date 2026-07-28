"""HTTP session and adapter classes for backend API communication."""

import logging
import time

from urllib3.util import Retry
import requests
from requests import Session
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)


class HttpClient:
    """Basic HTTP client with bearer token auth."""
    auth_type: str = "bearer"

    SUPPORTED_AUTH_TYPES = ["bearer"]

    def __init__(self, base_uri: str, token: str = "", session=None):
        self._base_uri = base_uri.rstrip("/")
        self._session = session or requests.Session()
        self._token = token
        self.setup_auth()

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str):
        self._token = value
        self.setup_auth()

    def setup_auth(self):
        if not self._token:
            return

        if not self.auth_type:
            raise ValueError("Auth type must be specified for setup")

        if not self.auth_type.lower() in self.SUPPORTED_AUTH_TYPES:
            raise ValueError(f"Unsupported auth type: {self.auth_type}")

        if self.auth_type.lower() == "bearer":
            self._set_bearer_token()

    def _set_bearer_token(self):
        self._session.headers.update(
            {"Authorization": f"Bearer {self._token}"}
        )

    def request(
        self,
        method: str,
        path: str,
        raise_for_status: bool = True,
        **kwargs,
    ) -> requests.Response:
        url = f"{self._base_uri}/{path.lstrip('/')}"
        response = self._session.request(method, url, timeout=10, **kwargs)
        if raise_for_status:
            response.raise_for_status()
        return response

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> requests.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs) -> requests.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.request("DELETE", path, **kwargs)


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

    timeout = 10
    default_raise_for_status = True

    @property
    def base_url(self) -> str:
        return self.adapter.base_url

    def __init__(
        self,
        adapter: BaseHttpAdapter,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.mount_adapters(adapter)

    def send(self, request, **kwargs):
        kwargs["timeout"] = kwargs.pop("timeout", self.timeout)
        return super().send(request, **kwargs)

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
    """HTTP adapter that handles login and automatic token refresh on 401/403/429."""

    oauth_status_codes = {401, 403, 429}
    oauth_backoff_factor = 0.5
    oauth_retry_limit = 1

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

            request.headers["Authorization"] = f"Bearer {self.access_token}"
            response = super().send(request, timeout=timeout, **kwargs)
            if response.status_code not in self.oauth_status_codes:
                response.raise_for_status()

        return response

    def _log_refresh_error(self, response, attempt, backoff):
        tpl = "Auth failure (%d), refresh token retry %d/%d in %.1fs"
        logger.error(tpl, response.status_code, attempt, self.oauth_retry_limit, backoff)


class BackendAdapter(OAuthAdapter):
    """Adapter for backend API authentication."""

    def login(self):
        """Exchange username/password for token."""
        response = requests.post(
            f"{self.base_url}/login",
            data={'username': self.username, 'password': self.password},
            headers={'Accept': 'application/json'},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response

    def refresh_tokens(self):
        """Refresh token by logging in again."""
        response = self.login()
        data = response.json()
        self.access_token = data['token']


class BackendSession(BaseSession):
    """Session for backend API with automatic token refresh."""
