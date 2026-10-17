import json
from unittest.mock import MagicMock

import pytest
import requests
from click.testing import CliRunner

from fncli.cli import cli
from fncli.cmds.mirror import MirrorConfig
from fncli.dagster.mirror import MirrorAPI


def response(body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


@pytest.fixture(autouse=True)
def mirror_env(monkeypatch):
    monkeypatch.setenv("MIRROR_API_TOKEN", "tok")
    monkeypatch.delenv("MIRROR_URL", raising=False)


@pytest.fixture
def session(monkeypatch):
    session = MagicMock()
    real_init = MirrorAPI.__init__

    def init(self, base_uri, token="", session_=None):
        real_init(self, base_uri, token, session=session)

    monkeypatch.setattr(MirrorAPI, "__init__", init)
    return session


def run(*args):
    result = CliRunner().invoke(cli, ["mirror", *args])
    assert result.exit_code == 0, result.output
    return result


def test_config_defaults_to_the_port_forwarded_service():
    assert MirrorConfig().mirror_url == "http://localhost:5050"


def test_the_token_is_required(monkeypatch):
    monkeypatch.delenv("MIRROR_API_TOKEN")

    result = CliRunner().invoke(cli, ["mirror", "list"])

    assert result.exit_code != 0


def test_add_posts_the_mirror(session):
    session.request.return_value = response({"id": 1})

    result = run(
        "add", "--upstream-uri", "https://github.com/o/r", "--secret-namespace", "fn",
        "--secret-key", "gh", "--gitea-owner", "mirrors", "--gitea-repo", "r", "--base-branch", "main",
    )

    method, url = session.request.call_args.args
    assert (method, url) == ("POST", "http://localhost:5050/mirrors")
    assert session.request.call_args.kwargs["json"] == {
        "upstream_uri": "https://github.com/o/r", "secret_namespace": "fn", "secret_key": "gh",
        "gitea_owner": "mirrors", "gitea_repo": "r", "base_branch": "main", "enabled": True,
    }
    assert json.loads(result.output) == {"id": 1}


def test_the_bearer_token_is_sent(monkeypatch):
    from fncli.cmds.mirror import build_mirror_api

    api = build_mirror_api()

    assert api._session.headers["Authorization"] == "Bearer tok"


def test_an_in_cluster_url_goes_through_localhost(monkeypatch):
    from fncli.cmds.mirror import build_mirror_api

    monkeypatch.setenv("MIRROR_URL", "http://gitea-mirror.fn.svc:8080")

    assert build_mirror_api()._base_uri == "http://localhost:8080"


@pytest.mark.parametrize("args, method, path", [
    (["list"], "GET", "/mirrors"),
    (["status", "3"], "GET", "/mirrors/3/status"),
    (["resync", "3"], "POST", "/mirrors/3/resync"),
    (["users-sync", "3"], "POST", "/mirrors/3/users/sync"),
    (["delete", "3"], "DELETE", "/mirrors/3"),
    (["webhook", "delete", "2"], "DELETE", "/webhooks/2"),
    (["webhook", "list"], "GET", "/webhooks"),
    (["webhook", "deliveries", "2"], "GET", "/webhooks/2/deliveries"),
])
def test_commands_call_their_endpoint(session, args, method, path):
    session.request.return_value = response({"ok": True})

    run(*args)

    assert session.request.call_args.args == (method, f"http://localhost:5050{path}")


def test_webhook_add_body(session):
    session.request.return_value = response({"id": 2})

    run(
        "webhook", "add", "--url", "http://backend.fn.svc/hook", "--secret-namespace", "fn",
        "--secret-key", "hmac", "--mirror-id", "1",
    )

    assert session.request.call_args.kwargs["json"] == {
        "url": "http://backend.fn.svc/hook", "secret_namespace": "fn", "secret_key": "hmac",
        "mirror_id": 1, "enabled": True,
    }


def test_deliveries_filters_by_status(session):
    session.request.return_value = response([])

    run("webhook", "deliveries", "2", "--status", "failed")

    assert session.request.call_args.kwargs["params"] == {"status": "failed"}


def test_an_error_response_fails_the_command(session):
    resp = response({"error": "x"}, 404)
    resp.raise_for_status.side_effect = RuntimeError("404")
    session.request.return_value = resp

    result = CliRunner().invoke(cli, ["mirror", "status", "9"])

    assert result.exit_code != 0


@pytest.mark.parametrize("args, path, enabled", [
    (["disable", "3"], "/mirrors/3", False),
    (["enable", "3"], "/mirrors/3", True),
    (["webhook", "disable", "2"], "/webhooks/2", False),
    (["webhook", "enable", "2"], "/webhooks/2", True),
])
def test_enable_and_disable_patch_enabled(session, args, path, enabled):
    session.request.return_value = response({"id": 1, "enabled": enabled})

    result = run(*args)

    assert session.request.call_args.args == ("PATCH", f"http://localhost:5050{path}")
    assert session.request.call_args.kwargs["json"] == {"enabled": enabled}
    assert json.loads(result.output)["enabled"] is enabled


def test_delete_reports_the_id(session):
    session.request.return_value = response(None, 204)

    result = run("delete", "3")

    assert json.loads(result.output) == {"deleted": 3}


def test_there_is_no_redeliver_command():
    result = CliRunner().invoke(cli, ["mirror", "webhook", "redeliver", "1"])

    assert result.exit_code != 0


@pytest.mark.parametrize("status", [400, 409, 502])
def test_the_services_error_message_is_shown(session, status):
    resp = response({"error": "another sync holds the lock"}, status)
    resp.raise_for_status.side_effect = requests.HTTPError("boom", response=resp)
    session.request.return_value = resp

    result = CliRunner().invoke(cli, ["mirror", "resync", "3"])

    assert result.exit_code != 0
    assert f"HTTP {status}: another sync holds the lock" in result.output
    assert "Traceback" not in result.output


def test_an_error_without_a_json_body_still_fails_cleanly(session):
    resp = response(None, 502)
    resp.json.side_effect = ValueError("no json")
    resp.raise_for_status.side_effect = requests.HTTPError("502 Bad Gateway", response=resp)
    session.request.return_value = resp

    result = CliRunner().invoke(cli, ["mirror", "list"])

    assert result.exit_code != 0
    assert "502" in result.output
