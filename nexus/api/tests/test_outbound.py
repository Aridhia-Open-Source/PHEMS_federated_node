"""The shared outbound client layer (app/clients/outbound.py) and the /health_check that uses it."""
import re
from pathlib import Path

import pytest
import requests
import responses
from kubernetes import client as k8s
from urllib3.exceptions import MaxRetryError, ReadTimeoutError

from app import main
from app.clients import outbound
from app.database import query_validator
from app.clients.keycloak import URLS
from app.clients.kubernetes import OutboundApiClient
from app.clients.outbound import OutboundError, OutboundSession, OutboundTimeout, ttl_cache

URL = "http://service.test/thing"


@pytest.fixture
def http(monkeypatch):
    """A fresh session with no retry backoff, so 429 tests don't sleep."""
    monkeypatch.setattr(outbound, "BACKOFF_FACTOR", 0)
    return OutboundSession("service")


@pytest.fixture(autouse=True)
def clear_health_cache():
    main.keycloak_is_up.cache_clear()
    yield
    main.keycloak_is_up.cache_clear()


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


# ---------------------------------------------------------------- session

def test_default_timeout_is_applied(http, mocker):
    send = mocker.spy(requests.Session, "send")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, URL, status=200)
        http.get(URL)
    assert send.call_args.kwargs["timeout"] == (outbound.CONNECT_TIMEOUT, outbound.READ_TIMEOUT)


def test_per_call_timeout_overrides_the_default(http, mocker):
    send = mocker.spy(requests.Session, "send")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, URL, status=200)
        http.get(URL, timeout=(1, 2))
    assert send.call_args.kwargs["timeout"] == (1, 2)


def test_per_service_timeout():
    assert OutboundSession("slow", timeout=(5, 30)).timeout == (5, 30)


def test_session_is_shared_per_service():
    assert outbound.session("shared-test") is outbound.session("shared-test")
    assert outbound.session("shared-test") is not outbound.session("other-test")


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_429_is_retried(http, method):
    with responses.RequestsMock() as rsps:
        rsps.add(method, URL, status=429)
        rsps.add(method, URL, status=201)
        assert http.request(method, URL).status_code == 201
        assert len(rsps.calls) == 2


def test_last_429_is_returned_not_raised(http):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, URL, status=429)
        assert http.post(URL).status_code == 429
        assert len(rsps.calls) == outbound.RETRY_LIMIT + 1


def test_other_errors_are_not_retried(http):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, URL, status=503)
        assert http.post(URL).status_code == 503
        assert len(rsps.calls) == 1


def test_timeout_is_a_504(http):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, URL, body=requests.ReadTimeout("slow"))
        with pytest.raises(OutboundTimeout) as err:
            http.post(URL)
        assert len(rsps.calls) == 1
    assert err.value.code == 504 and err.value.description == "service did not answer in time"


def test_connection_failure_is_a_502(http):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, URL, body=requests.ConnectionError("down"))
        with pytest.raises(OutboundError) as err:
            http.get(URL)
    assert err.value.code == 502 and err.value.description == "service is unreachable: ConnectionError"


def test_cookies_are_never_kept(http):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, URL, status=200, headers={"Set-Cookie": "AUTH_SESSION_ID=abc; Path=/"})
        http.get(URL)
    assert not http.cookies


# ---------------------------------------------------------------- ttl_cache

def test_cache_hit_and_expiry():
    clock, calls = Clock(), []

    @ttl_cache(5, clock=clock)
    def read(key):
        calls.append(key)
        return len(calls)

    assert read("a") == read("a") == 1
    assert read("b") == 2
    clock.now = 5
    assert read("a") == 3


def test_cache_keeps_an_outbound_error_for_the_window():
    clock, calls = Clock(), []

    @ttl_cache(5, clock=clock)
    def read():
        calls.append(1)
        raise OutboundError("down")

    for _ in range(3):
        with pytest.raises(OutboundError):
            read()
    assert len(calls) == 1
    clock.now = 5
    with pytest.raises(OutboundError):
        read()
    assert len(calls) == 2


# ---------------------------------------------------------------- /health_check

def test_health_check_flood_makes_one_keycloak_call(client):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, URLS["health_check"], status=200)
        for _ in range(10):
            response = client.get("/health_check")
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "keycloak": True}
        assert len(rsps.calls) == 1


def test_health_check_uses_the_short_timeout(client, mocker):
    send = mocker.spy(requests.Session, "send")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, URLS["health_check"], status=200)
        client.get("/health_check")
    assert send.call_args.kwargs["timeout"] == main.HEALTH_CHECK_TIMEOUT


@pytest.mark.parametrize("answer", [
    {"status": 500}, {"body": requests.ConnectionError("down")}, {"body": requests.ReadTimeout("slow")},
])
def test_health_check_keycloak_down_is_502(client, answer):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, URLS["health_check"], **answer)
        response = client.get("/health_check")
    assert response.status_code == 502
    assert response.json() == {"status": "non operational", "keycloak": False}


# ---------------------------------------------------------------- Kubernetes and datasets

def test_kubernetes_calls_get_the_default_timeout(mocker):
    call_api = mocker.patch.object(k8s.ApiClient, "call_api")
    OutboundApiClient().call_api("/api/v1/secrets", "GET")
    assert call_api.call_args.kwargs["_request_timeout"] == (outbound.CONNECT_TIMEOUT, outbound.READ_TIMEOUT)
    OutboundApiClient().call_api("/api/v1/secrets", "GET", _request_timeout=60)
    assert call_api.call_args.kwargs["_request_timeout"] == 60


@pytest.mark.parametrize("error, typed, code", [
    (ReadTimeoutError(None, "/api", "slow"), OutboundTimeout, 504),
    (MaxRetryError(None, "/api"), OutboundError, 502),
])
def test_kubernetes_network_errors_are_typed(mocker, error, typed, code):
    mocker.patch.object(k8s.ApiClient, "call_api", side_effect=error)
    with pytest.raises(typed) as err:
        OutboundApiClient().call_api("/api/v1/secrets", "GET")
    assert err.value.code == code


def test_kubernetes_api_errors_pass_through(mocker):
    mocker.patch.object(k8s.ApiClient, "call_api", side_effect=k8s.exceptions.ApiException(status=404))
    with pytest.raises(k8s.exceptions.ApiException):
        OutboundApiClient().call_api("/api/v1/secrets", "GET")


def test_query_validation_connects_with_a_timeout(mocker):
    engine = mocker.patch.object(query_validator, "create_engine")
    mocker.patch.object(query_validator, "sessionmaker")
    dataset = mocker.Mock(type="postgres", host="db", port=5432)
    dataset.name = "data"
    dataset.get_credentials.return_value = ("user", "pass")
    query_validator.connect_to_dataset(dataset)
    assert engine.call_args.kwargs["connect_args"] == {"connect_timeout": query_validator.CONNECTION_TIMEOUT}


# ---------------------------------------------------------------- the guard

BARE_CALL = re.compile(r"\brequests\.(get|post|put|patch|delete|head|options|request|Session)\(")


def test_no_outbound_call_bypasses_the_layer():
    """New services go through app/clients/outbound.py, so every call has a timeout, retries and typed errors."""
    app_dir = Path(main.__file__).parent
    offenders = [
        f"{path.relative_to(app_dir)}:{n}"
        for path in app_dir.rglob("*.py") if path.name != "outbound.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if BARE_CALL.search(line)
    ]
    assert not offenders, f"use app.clients.outbound.session(...) instead of bare requests: {offenders}"
