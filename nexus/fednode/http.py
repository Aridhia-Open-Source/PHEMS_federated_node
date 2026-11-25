"""
The outbound HTTP layer every federated node service uses (ADR 0039).

A default (connect, read) timeout a service or a call can override; only a 429 is retried, for every method, and a
read timeout never is; a timeout or a connection failure is a `ClientTimeout` or a `ClientError`, never a raw
`requests` exception. A status error still raises `requests.HTTPError`, for callers that read the status.
"""

import logging
import time
from contextlib import contextmanager
from http.cookiejar import DefaultCookiePolicy
from pathlib import Path

from urllib3.util import Retry
import requests
from requests import Session
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = (3, 10)


class ClientError(Exception):
    """A service this one calls could not be reached, or answered with an error of its own."""


class ClientTimeout(ClientError):
    """A service this one calls did not answer in time."""


@contextmanager
def transport_errors():
    """A timeout or a connection failure in the block is a ClientTimeout or a ClientError. A status error is not."""
    try:
        yield
    except requests.HTTPError:
        raise
    except requests.Timeout as err:
        raise ClientTimeout(f"The service did not answer in time: {err}") from err
    except requests.RequestException as err:
        raise ClientError(f"The service is unreachable: {type(err).__name__}") from err


class HttpClient:
    """Basic HTTP client with bearer token auth."""
    auth_type: str = "bearer"

    SUPPORTED_AUTH_TYPES = ["bearer"]

    def __init__(self, base_uri: str, token: str = "", session=None, timeout: tuple[float, float] = DEFAULT_TIMEOUT):
        self._base_uri = base_uri.rstrip("/")
        self._session = session or self.new_session()
        self._timeout = timeout
        self._token = token
        self.setup_auth()

    @staticmethod
    def new_session(keep_cookies: bool = False) -> Session:
        """
        A session with the 429 retry mounted. It keeps no cookies unless asked to, as one client serves every request
        of a service; only a client that signs in the way a browser does needs them.
        """
        session = Session()
        if not keep_cookies:
            session.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))
        adapter = RetryAdapter()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

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

        if self.auth_type.lower() not in self.SUPPORTED_AUTH_TYPES:
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
        kwargs.setdefault("timeout", self._timeout)
        with transport_errors():
            response = self._session.request(method, url, **kwargs)
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


class RetryAdapter(HTTPAdapter):
    """Base HTTP adapter: the default timeout, and a 429 retried with backoff."""

    retry_limit = 3
    backoff_factor = 0.5
    default_timeout = DEFAULT_TIMEOUT
    retry_status_forcelist = {429}
    # urllib3 honours Retry-After up to 6 hours by default; a long 429 would stall a sensor tick or an operator handler
    retry_after_max = 5

    def __init__(
        self,
        base_url: str = '',
        timeout: int | None = None,
        max_retries: Retry | None = None,
        **kwargs
    ):
        self.base_url = base_url
        self.timeout = timeout or self.default_timeout
        # Mounted, so a 429 is retried with backoff before the response comes back
        super().__init__(**{**kwargs, 'max_retries': max_retries or self.default_retry})

    @property
    def default_retry(self):
        return Retry(
            total=self.retry_limit,
            # Only a 429 is retried: a read that timed out may have done its work (a created user), so it is not
            read=0,
            connect=0,
            backoff_factor=self.backoff_factor,
            status_forcelist=self.retry_status_forcelist,
            # A 429 means the request was not processed, so retrying a POST is safe
            allowed_methods=None,
            retry_after_max=self.retry_after_max,
            # When the retries run out the last response comes back, so raise_for_status and the
            # OAuth adapter still see the status rather than a urllib3 MaxRetryError
            raise_on_status=False,
        )

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        if timeout is None:
            timeout = self.timeout
        return super().send(
            request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies
        )


class BaseSession(Session):
    """Base session with base URL support."""

    timeout = DEFAULT_TIMEOUT
    default_raise_for_status = True

    @property
    def base_url(self) -> str:
        return self.adapter.base_url

    def __init__(
        self,
        adapter: RetryAdapter,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.mount_adapters(adapter)

    def send(self, request, **kwargs):
        kwargs["timeout"] = kwargs.pop("timeout", self.timeout)
        return super().send(request, **kwargs)

    def request(self, method, url, *args, raise_for_status: bool | None = None, **kwargs):
        full_url = f"{self.base_url}/{url.lstrip('/')}"
        with transport_errors():
            response = super().request(method, full_url, *args, **kwargs)
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


class OAuthAdapter(RetryAdapter):
    """HTTP adapter that handles login and automatic token refresh on 401/403/429."""

    oauth_status_codes = {401, 403, 429}
    oauth_backoff_factor = 0.5
    oauth_retry_limit = 1

    def __init__(self, base_url: str, username: str, password: str, timeout: tuple[float, float] = DEFAULT_TIMEOUT):
        super().__init__(base_url=base_url, timeout=timeout)
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

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        if self.access_token:
            request.headers["Authorization"] = f"Bearer {self.access_token}"

        if timeout is None:
            timeout = self.timeout
        options = {"stream": stream, "verify": verify, "cert": cert, "proxies": proxies}
        response = super().send(request, timeout=timeout, **options)
        if response.status_code not in self.oauth_status_codes:
            return response

        return self._retry_on_auth_failure(request, response, timeout, **options)

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


class PasswordFileAdapter(BackendAdapter):
    """
    Reads the password from the mounted Secret at every login: a credential rotation patches the Secret,
    and the next 401 logs in again with the new one, without a restart.
    """

    def __init__(self, base_url: str, username: str, password_file: str, timeout: tuple[float, float] = DEFAULT_TIMEOUT):
        super().__init__(base_url=base_url, username=username, password="", timeout=timeout)
        self.password_file = password_file

    def login(self):
        self.password = Path(self.password_file).read_text(encoding="utf-8").strip()
        return super().login()


class BackendSession(BaseSession):
    """Session for backend API with automatic token refresh."""
