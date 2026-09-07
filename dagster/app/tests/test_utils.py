from unittest.mock import MagicMock, patch

import pytest
import requests

from app.utils import (
    BackendAdapter,
    BackendSession,
    BaseHttpAdapter,
    HttpClient,
    OAuthAdapter,
)


def response(status_code=200, body=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = body or {}
    return resp


class TestHttpClient:
    def test_trailing_slash_is_stripped_from_the_base_uri(self):
        client = HttpClient("https://api.github.com/", session=MagicMock())

        assert client._base_uri == "https://api.github.com"

    def test_no_auth_header_without_a_token(self):
        session = MagicMock()

        HttpClient("https://api.github.com", session=session)

        session.headers.update.assert_not_called()

    def test_bearer_token_is_set(self):
        session = MagicMock()

        HttpClient("https://api.github.com", token="abc", session=session)

        session.headers.update.assert_called_once_with({"Authorization": "Bearer abc"})

    def test_setting_the_token_re_authenticates(self):
        session = MagicMock()
        client = HttpClient("https://api.github.com", session=session)

        client.token = "new"

        assert client.token == "new"
        session.headers.update.assert_called_once_with({"Authorization": "Bearer new"})

    def test_unsupported_auth_type_is_rejected(self):
        client = HttpClient("https://api.github.com", session=MagicMock())
        client.auth_type = "basic"

        with pytest.raises(ValueError, match="Unsupported auth type"):
            client.token = "abc"

    def test_missing_auth_type_is_rejected(self):
        client = HttpClient("https://api.github.com", session=MagicMock())
        client.auth_type = ""

        with pytest.raises(ValueError, match="Auth type must be specified"):
            client.token = "abc"

    def test_paths_are_joined_onto_the_base_uri(self):
        session = MagicMock()
        session.request.return_value = response()
        client = HttpClient("https://api.github.com", session=session)

        client.get("/repos/org/repo")

        assert session.request.call_args.args == ("GET", "https://api.github.com/repos/org/repo")

    def test_requests_are_raised_for_status_by_default(self):
        session = MagicMock()
        session.request.return_value = response()
        client = HttpClient("https://api.github.com", session=session)

        client.post("path", json={})

        session.request.return_value.raise_for_status.assert_called_once()

    def test_raise_for_status_can_be_disabled(self):
        session = MagicMock()
        session.request.return_value = response(404)
        client = HttpClient("https://api.github.com", session=session)

        client.request("GET", "path", raise_for_status=False)

        session.request.return_value.raise_for_status.assert_not_called()

    def test_verbs_map_onto_methods(self):
        session = MagicMock()
        session.request.return_value = response()
        client = HttpClient("https://api.github.com", session=session)

        for verb in ("get", "post", "patch", "put", "delete"):
            getattr(client, verb)("path")

        methods = [call.args[0] for call in session.request.call_args_list]
        assert methods == ["GET", "POST", "PATCH", "PUT", "DELETE"]


class TestBaseHttpAdapter:
    def test_default_retry_settings(self):
        retry = BaseHttpAdapter(base_url="https://backend").default_retry

        assert retry.total == 3
        assert 429 in retry.status_forcelist

    def test_timeout_is_applied_to_sends(self):
        adapter = BaseHttpAdapter(base_url="https://backend", timeout=5)

        with patch("requests.adapters.HTTPAdapter.send") as send:
            adapter.send(MagicMock())

        assert send.call_args.kwargs["timeout"] == 5

    def test_caller_timeout_wins(self):
        adapter = BaseHttpAdapter(base_url="https://backend", timeout=5)

        with patch("requests.adapters.HTTPAdapter.send") as send:
            adapter.send(MagicMock(), timeout=1)

        assert send.call_args.kwargs["timeout"] == 1


class TestBaseSession:
    def test_relative_urls_are_resolved_against_the_adapter_base_url(self):
        session = BackendSession(adapter=BaseHttpAdapter(base_url="https://backend"))

        with patch("requests.Session.request", return_value=response()) as request:
            session.get("/datasets")

        assert request.call_args.args[1] == "https://backend/datasets"

    def test_base_url_comes_from_the_adapter(self):
        session = BackendSession(adapter=BaseHttpAdapter(base_url="https://backend"))

        assert session.base_url == "https://backend"

    def test_errors_raise_by_default(self):
        session = BackendSession(adapter=BaseHttpAdapter(base_url="https://backend"))
        resp = response(500)

        with patch("requests.Session.request", return_value=resp):
            session.get("/datasets")

        resp.raise_for_status.assert_called_once()

    def test_raise_for_status_can_be_disabled_per_request(self):
        session = BackendSession(adapter=BaseHttpAdapter(base_url="https://backend"))
        resp = response(404)

        with patch("requests.Session.request", return_value=resp):
            session.get("/datasets", raise_for_status=False)

        resp.raise_for_status.assert_not_called()

    def test_the_adapter_is_mounted_for_both_schemes(self):
        adapter = BaseHttpAdapter(base_url="https://backend")
        session = BackendSession(adapter=adapter)

        assert session.adapters["http://"] is adapter
        assert session.adapters["https://"] is adapter


class TestOAuthAdapter:
    @pytest.fixture
    def adapter(self):
        adapter = OAuthAdapter(base_url="https://backend", username="u", password="p")
        adapter.refresh_tokens = MagicMock(
            side_effect=lambda: setattr(adapter, "access_token", "token")
        )
        return adapter

    def test_the_token_is_fetched_lazily(self, adapter):
        assert adapter._access_token is None

        assert adapter.access_token == "token"
        adapter.refresh_tokens.assert_called_once()

    def test_the_token_is_reused(self, adapter):
        adapter.access_token = "cached"

        assert adapter.access_token == "cached"
        adapter.refresh_tokens.assert_not_called()

    def test_requests_are_authorised(self, adapter):
        request = MagicMock()
        request.headers = {}

        with patch("requests.adapters.HTTPAdapter.send", return_value=response()):
            adapter.send(request)

        assert request.headers["Authorization"] == "Bearer token"

    def test_a_successful_response_is_returned_untouched(self, adapter):
        ok = response()

        with patch("requests.adapters.HTTPAdapter.send", return_value=ok):
            assert adapter.send(MagicMock(headers={})) is ok
        adapter.refresh_tokens.assert_called_once()

    @pytest.mark.parametrize("status", [401, 403, 429])
    def test_auth_failures_refresh_the_token_and_retry(self, adapter, status):
        request = MagicMock()
        request.headers = {}
        adapter.access_token = "stale"
        responses = [response(status), response(200)]

        with patch("app.utils.time.sleep") as sleep:
            with patch("requests.adapters.HTTPAdapter.send", side_effect=responses):
                result = adapter.send(request)

        assert result.status_code == 200
        assert request.headers["Authorization"] == "Bearer token"
        adapter.refresh_tokens.assert_called_once()
        sleep.assert_called_once()

    def test_a_still_failing_retry_is_returned_rather_than_looped(self, adapter):
        adapter.access_token = "stale"
        responses = [response(401), response(401)]

        with patch("app.utils.time.sleep"):
            with patch("requests.adapters.HTTPAdapter.send", side_effect=responses):
                result = adapter.send(MagicMock(headers={}))

        assert result.status_code == 401
        assert adapter.refresh_tokens.call_count == 1

    def test_refresh_tokens_is_abstract(self):
        adapter = OAuthAdapter(base_url="https://backend", username="u", password="p")

        with pytest.raises(NotImplementedError):
            adapter.refresh_tokens()


class TestBackendAdapter:
    def test_login_posts_the_credentials(self):
        adapter = BackendAdapter(base_url="https://backend", username="u", password="p")

        with patch("app.utils.requests.post", return_value=response(body={"token": "t"})) as post:
            adapter.login()

        assert post.call_args.args[0] == "https://backend/login"
        assert post.call_args.kwargs["data"] == {"username": "u", "password": "p"}

    def test_refresh_tokens_stores_the_token(self):
        adapter = BackendAdapter(base_url="https://backend", username="u", password="p")

        with patch("app.utils.requests.post", return_value=response(body={"token": "t"})):
            adapter.refresh_tokens()

        assert adapter._access_token == "t"

    def test_a_failed_login_raises(self):
        adapter = BackendAdapter(base_url="https://backend", username="u", password="p")
        resp = response(401)
        resp.raise_for_status.side_effect = requests.HTTPError("401")

        with patch("app.utils.requests.post", return_value=resp):
            with pytest.raises(requests.HTTPError):
                adapter.login()
