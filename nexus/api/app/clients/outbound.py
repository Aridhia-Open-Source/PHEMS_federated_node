"""
The one way nexus-api makes outbound HTTP calls (issue #674).

Each service gets one shared `requests.Session` (`session("keycloak")`), so connections are reused, every call has a
`(connect, read)` timeout, a 429 is retried with backoff, and a timeout or a connection failure is an `OutboundError`
(504 or 502) instead of a raw `requests` exception. `ttl_cache` caches idempotent reads; never use it on writes.

The timeout and retry values match nexus_client.http (Dagster, fncli and the operator), so both sides behave alike.
"""

import os
import threading
import time
from functools import wraps
from http.cookiejar import DefaultCookiePolicy

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from app.helpers.exceptions import LogAndException

CONNECT_TIMEOUT = float(os.getenv("OUTBOUND_CONNECT_TIMEOUT", "3"))
READ_TIMEOUT = float(os.getenv("OUTBOUND_READ_TIMEOUT", "10"))
RETRY_LIMIT = 3
RETRY_AFTER_MAX = 5
BACKOFF_FACTOR = 0.5
# Matches the FastAPI threadpool (40), so concurrent requests don't churn connections
POOL_SIZE = 40


class OutboundError(LogAndException):
    """A service nexus-api calls could not be reached."""
    code = 502


class OutboundTimeout(OutboundError):
    """A service nexus-api calls did not answer in time."""
    code = 504


class OutboundSession(requests.Session):
    """
    A session for one service: default timeout, 429 retry, typed errors.

    It is shared by every request nexus-api serves, so it keeps no cookies and must never carry an Authorization
    header of its own: pass credentials per call.
    """

    def __init__(self, name: str, timeout: tuple[float, float] | None = None):
        super().__init__()
        self.name = name
        self.timeout = timeout or (CONNECT_TIMEOUT, READ_TIMEOUT)
        self.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))
        retry = Retry(
            total=RETRY_LIMIT,
            # Only a 429 is retried: a timed-out read may have done its work (a created user), so it is not
            read=0,
            connect=0,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist={429},
            # A 429 means the request was not processed, so retrying a POST is safe
            allowed_methods=None,
            respect_retry_after_header=True,
            # urllib3 honours Retry-After up to 6 hours, outside the read timeout: a long 429 would hold request
            # threads, and keycloak_is_up holds its cache lock meanwhile
            retry_after_max=RETRY_AFTER_MAX,
            # The last 429 comes back as a response, for callers to check like any other status
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=POOL_SIZE, pool_maxsize=POOL_SIZE)
        self.mount("http://", adapter)
        self.mount("https://", adapter)

    def request(self, method, url, *args, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        try:
            return super().request(method, url, *args, **kwargs)
        except requests.Timeout as err:
            raise OutboundTimeout(f"{self.name} did not answer in time") from err
        except requests.RequestException as err:
            raise OutboundError(f"{self.name} is unreachable: {type(err).__name__}") from err


_sessions: dict[str, OutboundSession] = {}
_sessions_lock = threading.Lock()


def session(name: str, timeout: tuple[float, float] | None = None) -> OutboundSession:
    """The shared session for a service; `timeout` applies when it is first made."""
    with _sessions_lock:
        if name not in _sessions:
            _sessions[name] = OutboundSession(name, timeout)
        return _sessions[name]


def ttl_cache(seconds: float, clock=time.monotonic):
    """
    Caches a function's result per arguments for `seconds`, for idempotent reads only.

    One caller fetches while the others wait, so a flood makes one call per window. An `OutboundError` is cached too:
    an outage is when the service can least afford a retry storm. `.cache_clear()` empties it.
    """
    def decorator(func):
        entries: dict[tuple, tuple[float, object, OutboundError | None]] = {}
        lock = threading.Lock()

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            with lock:
                entry = entries.get(key)
                if entry is None or clock() - entry[0] >= seconds:
                    try:
                        entry = (clock(), func(*args, **kwargs), None)
                    except OutboundError as err:
                        entry = (clock(), None, err)
                    entries[key] = entry
            if entry[2] is not None:
                raise entry[2]
            return entry[1]

        wrapper.cache_clear = entries.clear
        return wrapper
    return decorator
