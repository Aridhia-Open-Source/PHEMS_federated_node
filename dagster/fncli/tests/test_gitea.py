from unittest.mock import MagicMock

import pytest

from fncli.gitea import OAUTH_REDIRECT_URI, GiteaAdminAPI, GiteaWebClient, hidden_inputs

CALLBACK = "http://localhost/fn-callback"
CONSENT_PAGE = """
<form class="stopwatch-commit" method="post"><button type="submit"></button></form>
<form method="post" action="/login/oauth/grant">
  <input type="hidden" name="client_id" value="cid">
  <input type="hidden" name="state" value="fncli">
  <input type="hidden" name="scope" value="">
  <input type="hidden" name="redirect_uri" value="http://localhost/fn-callback">
  <button type="submit" name="granted" value="true">Authorize Application</button>
</form>
"""


def response(status_code=200, text="", headers=None, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.json.return_value = body
    return resp


class FakeSession:
    """Answers each request from a script of (method, path suffix) -> response, and records them."""

    def __init__(self, script):
        self.script = script
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for (script_method, suffix), answer in self.script.items():
            if method == script_method and url.endswith(suffix):
                return answer
        raise AssertionError(f"Unscripted request {method} {url}")


def web_client(script):
    session = FakeSession(script)
    return GiteaWebClient("fnsvc", "pw", session=session, base_uri="http://localhost:4000"), session


def test_hidden_inputs_are_the_hidden_fields_only():
    page = '<input type="text" name="user_name"><input type="hidden" name="_csrf" value="tok"><input type="hidden" name="empty">'

    assert hidden_inputs(page) == {"_csrf": "tok", "empty": ""}


def test_login_posts_the_credentials_without_a_csrf_token_when_the_page_has_none():
    web, session = web_client({
        ("GET", "/user/login"): response(text="<form><input name='user_name'></form>"),
        ("POST", "/user/login"): response(303),
    })

    web.login()

    method, url, kwargs = session.calls[1]
    assert (method, url) == ("POST", "http://localhost:4000/user/login")
    assert kwargs["data"] == {"user_name": "fnsvc", "password": "pw"}
    assert kwargs["allow_redirects"] is False


def test_login_sends_the_csrf_token_an_older_gitea_puts_on_the_page():
    web, session = web_client({
        ("GET", "/user/login"): response(text='<input type="hidden" name="_csrf" value="tok">'),
        ("POST", "/user/login"): response(303),
    })

    web.login()

    assert session.calls[1][2]["data"] == {"_csrf": "tok", "user_name": "fnsvc", "password": "pw"}


def test_login_fails_when_gitea_shows_the_form_again():
    web, _ = web_client({("GET", "/user/login"): response(), ("POST", "/user/login"): response(200)})

    with pytest.raises(RuntimeError, match="login as fnsvc failed"):
        web.login()


def test_authorize_returns_the_code_from_the_redirect_without_following_it():
    web, session = web_client({
        ("GET", "/login/oauth/authorize"): response(303, headers={"Location": f"{CALLBACK}?code=gta_abc&state=fncli"}),
    })

    assert web.authorize("cid", CALLBACK) == "gta_abc"

    kwargs = session.calls[0][2]
    assert kwargs["params"] == {
        "client_id": "cid", "redirect_uri": CALLBACK, "response_type": "code", "state": "fncli",
    }
    assert kwargs["allow_redirects"] is False
    assert len(session.calls) == 1


def test_authorize_grants_the_consent_form_the_first_time():
    web, session = web_client({
        ("GET", "/login/oauth/authorize"): response(200, text=CONSENT_PAGE),
        ("POST", "/login/oauth/grant"): response(303, headers={"Location": f"{CALLBACK}?code=gta_new&state=fncli"}),
    })

    assert web.authorize("cid", CALLBACK) == "gta_new"

    assert session.calls[1][2]["data"] == {
        "client_id": "cid", "state": "fncli", "scope": "", "redirect_uri": CALLBACK, "granted": "true",
    }


def test_authorize_fails_when_the_redirect_has_no_code():
    web, _ = web_client({
        ("GET", "/login/oauth/authorize"): response(303, headers={"Location": f"{CALLBACK}?error=access_denied"}),
    })

    with pytest.raises(RuntimeError, match="did not authorise"):
        web.authorize("cid", CALLBACK)


def test_exchange_code_posts_the_grant_and_returns_the_tokens():
    tokens = {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
    web, session = web_client({("POST", "/login/oauth/access_token"): response(body=tokens)})

    assert web.exchange_code("cid", "sec", "gta_abc", CALLBACK) == tokens

    kwargs = session.calls[0][2]
    assert kwargs["data"] == {
        "client_id": "cid", "client_secret": "sec", "grant_type": "authorization_code",
        "code": "gta_abc", "redirect_uri": CALLBACK,
    }
    assert kwargs["headers"] == {"Accept": "application/json"}


APP_FIELDS = {
    "name": "fn-sensor",
    "redirect_uris": [CALLBACK],
    "confidential_client": True,
    "skip_secondary_authorization": True,
}


def admin_api(script, web=None):
    session = FakeSession(script)
    client = MagicMock()
    client.request.side_effect = lambda method, path, **kwargs: session.request(method, path, **kwargs)
    return GiteaAdminAPI(client, "fnsvc", web or MagicMock(), logger=MagicMock()), session


def test_get_or_create_oauth_app_creates_one_that_skips_the_consent_screen():
    created = {"id": 4, "client_id": "cid", "client_secret": "sec"}
    api, session = admin_api({
        ("GET", "user/applications/oauth2"): response(body=[{"id": 1, "name": "other"}]),
        ("POST", "user/applications/oauth2"): response(body=created),
    })

    assert api.get_or_create_oauth_app("fn-sensor", CALLBACK) == created

    assert session.calls[1][2]["json"] == APP_FIELDS


def test_get_or_create_oauth_app_edits_an_existing_one_for_a_new_secret():
    edited = {"id": 4, "client_id": "cid", "client_secret": "new-secret"}
    api, session = admin_api({
        ("GET", "user/applications/oauth2"): response(body=[{"id": 4, "name": "fn-sensor"}]),
        ("PATCH", "user/applications/oauth2/4"): response(body=edited),
    })

    assert api.get_or_create_oauth_app("fn-sensor", CALLBACK) == edited

    assert [call[0] for call in session.calls] == ["GET", "PATCH"]
    assert session.calls[1][2]["json"] == APP_FIELDS


def test_delete_oauth_app_deletes_the_one_of_that_name():
    api, session = admin_api({
        ("GET", "user/applications/oauth2"): response(body=[{"id": 4, "name": "fn-sensor"}]),
        ("DELETE", "user/applications/oauth2/4"): response(204),
    })

    assert api.delete_oauth_app("fn-sensor") is True
    assert session.calls[1][:2] == ("DELETE", "user/applications/oauth2/4")


def test_delete_oauth_app_reports_when_there_is_none():
    api, session = admin_api({("GET", "user/applications/oauth2"): response(body=[])})

    assert api.delete_oauth_app("fn-sensor") is False
    assert len(session.calls) == 1


def test_authorize_oauth_app_logs_in_authorises_and_exchanges_the_code():
    web = MagicMock()
    web.authorize.return_value = "gta_abc"
    web.exchange_code.return_value = {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
    api, _ = admin_api({
        ("GET", "user/applications/oauth2"): response(body=[]),
        ("POST", "user/applications/oauth2"): response(body={"client_id": "cid", "client_secret": "sec"}),
    }, web)

    tokens = api.authorize_oauth_app("fn-sensor")

    web.login.assert_called_once_with()
    web.authorize.assert_called_once_with("cid", OAUTH_REDIRECT_URI)
    web.exchange_code.assert_called_once_with("cid", "sec", "gta_abc", OAUTH_REDIRECT_URI)
    assert tokens == {
        "client_id": "cid", "client_secret": "sec", "access_token": "a", "refresh_token": "r", "expires_in": 3600,
    }
