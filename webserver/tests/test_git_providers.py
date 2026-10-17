"""
Global git providers: /global/providers CRUD and its 409s, and what a disabled provider does to
the repositories on it.
"""
from unittest.mock import MagicMock

import pytest
import requests

from app.helpers.base_model import db
from app.models.git_provider import GitProvider

PROV = "/global/providers"
TRIG = "/global/repositories/triggers"
RES = "/global/repositories/results"


def body(**fields):
    return {
        "name": "github", "type": "github", "uri": "https://github.com", "api_uri": "https://api.github.com", **fields
    }


def assert_error(response, status):
    assert response.status_code == status, response.json
    assert isinstance(response.json.get("error"), str) and response.json["error"]


def set_locked(project, locked=True):
    project.locked = locked
    db.session.commit()


def fake_response(status_code, body=None, reason="Reason"):
    response = MagicMock(status_code=status_code, ok=status_code < 400, reason=reason)
    response.json.return_value = body
    return response


# ---------------------------------------------------------------- create, get and list

def test_create_get_and_list(client, admin_headers):
    created = client.post(PROV, json=body(uri="https://GitHub.com/"), headers=admin_headers)
    assert created.status_code == 201, created.json
    assert set(created.json) == {"id", "name", "type", "uri", "api_uri", "enabled", "created_at", "updated_at"}
    assert created.json | {"id": None, "created_at": None, "updated_at": None} == {
        **body(), "id": None, "enabled": True, "created_at": None, "updated_at": None
    }  # the uri is kept normalised

    mirror = client.post(PROV, json=body(
        name="gitea", type="gitea", uri="http://gitea:4000", api_uri="http://gitea:4000/api/v1", enabled=False,
    ), headers=admin_headers)
    assert mirror.status_code == 201, mirror.json
    assert mirror.json["enabled"] is False

    assert client.get(f"{PROV}/{created.json['id']}", headers=admin_headers).json == created.json
    assert [p["id"] for p in client.get(PROV, headers=admin_headers).json] == [created.json["id"], mirror.json["id"]]
    assert_error(client.get(f"{PROV}/999", headers=admin_headers), 404)


@pytest.mark.parametrize("changes", [
    {"uri": "https://git.example.com", "api_uri": "https://git.example.com/api"},  # the same name
    {"name": "other"},  # the same uri
    {"name": "other", "uri": "https://GitHub.com/"},  # the same uri, spelt differently
    {"name": "other", "uri": "https://github.com:443"},
])
def test_create_duplicate_name_or_uri_is_409(client, admin_headers, changes):
    assert client.post(PROV, json=body(), headers=admin_headers).status_code == 201
    assert_error(client.post(PROV, json=body(**changes), headers=admin_headers), 409)


@pytest.mark.parametrize("changes", [
    {"type": "gitlab"}, {"type": 5},
    {"uri": "github.com"}, {"uri": "ssh://github.com"}, {"uri": "https://user:pw@github.com"},
    {"api_uri": "https://evil.example.com"},  # the api has to be on the provider's own host
    {"api_uri": "https://user:pw@api.github.com"},
    {"name": ""}, {"enabled": "yes"},
    {"bogus": 1},
])
def test_create_invalid_is_400(client, admin_headers, changes):
    assert_error(client.post(PROV, json=body(**changes), headers=admin_headers), 400)


def test_create_missing_field_is_400(client, admin_headers):
    for missing in ("name", "type", "uri", "api_uri"):
        payload = body()
        del payload[missing]
        response = client.post(PROV, json=payload, headers=admin_headers)
        assert_error(response, 400)
        assert missing in response.json["error"]


# ---------------------------------------------------------------- patch

def test_patch_fields(client, admin_headers, git_provider):
    url = f"{PROV}/{git_provider.id}"
    renamed = client.patch(url, json={"name": "gh"}, headers=admin_headers)
    assert renamed.status_code == 200, renamed.json
    assert renamed.json["name"] == "gh"

    moved = client.patch(url, json={
        "uri": "https://git.example.org", "api_uri": "https://git.example.org/api", "enabled": False
    }, headers=admin_headers)
    assert moved.status_code == 200, moved.json
    assert (moved.json["uri"], moved.json["api_uri"], moved.json["enabled"]) == (
        "https://git.example.org", "https://git.example.org/api", False
    )


@pytest.mark.parametrize("changes", [
    {}, {"bogus": 1}, {"name": None}, {"name": ""}, {"type": "gitlab"}, {"uri": "ftp://x"}, {"enabled": "no"},
    {"api_uri": "https://evil.example.com"},
    {"uri": "https://git.example.com"},  # the api_uri is no longer on the uri's host
])
def test_patch_invalid_is_400(client, admin_headers, git_provider, changes):
    assert_error(client.patch(f"{PROV}/{git_provider.id}", json=changes, headers=admin_headers), 400)


def test_patch_to_a_taken_name_or_uri_is_409(client, admin_headers, git_provider, make_provider):
    other = make_provider("git.example.com", type="gitea")
    assert_error(client.patch(f"{PROV}/{other.id}", json={"name": git_provider.name}, headers=admin_headers), 409)
    assert_error(client.patch(
        f"{PROV}/{other.id}", json={"uri": "https://github.com", "api_uri": "https://api.github.com"}, headers=admin_headers
    ), 409)
    # its own name and uri are not a clash
    assert client.patch(f"{PROV}/{other.id}", json={"name": other.name, "uri": other.uri}, headers=admin_headers).status_code == 200


def test_patch_beyond_name_needs_linked_projects_drained(
        client, admin_headers, project, git_provider, linked_trigger_repo):
    url = f"{PROV}/{git_provider.id}"
    assert client.patch(url, json={"name": "renamed"}, headers=admin_headers).status_code == 200
    assert_error(client.patch(url, json={"enabled": False}, headers=admin_headers), 409)
    set_locked(project)
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).json["enabled"] is False


# ---------------------------------------------------------------- delete

def test_delete_204_then_404(client, admin_headers, git_provider):
    assert client.delete(f"{PROV}/{git_provider.id}", headers=admin_headers).status_code == 204
    assert_error(client.get(f"{PROV}/{git_provider.id}", headers=admin_headers), 404)


@pytest.mark.parametrize("make", ["global_trigger_repo", "global_results_repo"])
def test_delete_is_409_while_a_repository_is_on_it(client, admin_headers, request, git_provider, make):
    repo = request.getfixturevalue(make)
    assert_error(client.delete(f"{PROV}/{git_provider.id}", headers=admin_headers), 409)
    db.session.delete(repo)
    db.session.commit()
    assert client.delete(f"{PROV}/{git_provider.id}", headers=admin_headers).status_code == 204


# ---------------------------------------------------------------- a disabled provider

def test_disabled_provider_makes_its_repositories_inactive(
        client, admin_headers, project, git_provider, linked_trigger_repo, linked_results_repo, global_trigger_repo,
        make_provider, make_trigger_repo):
    project.enabled = True
    set_locked(project)
    T = global_trigger_repo.id
    elsewhere = make_trigger_repo(uri="git.example.com/org/elsewhere")  # a repository on another provider
    elsewhere_link = f"/projects/{project.id}/repositories/triggers/{elsewhere.id}"
    assert client.put(elsewhere_link, json={"watch_dir": "e"}, headers=admin_headers).status_code == 201
    trigger_links = f"/projects/{project.id}/repositories/triggers"
    results_links = f"/projects/{project.id}/repositories/results"
    active = lambda url: [x["active"] for x in client.get(url, headers=admin_headers).json]  # noqa: E731
    active_ids = lambda url: [  # noqa: E731
        x["trigger_repository"]["id"] for x in client.get(f"{url}?active=true", headers=admin_headers).json
    ]
    assert active(trigger_links) == [True, True] and active(results_links) == [True]
    assert [r["id"] for r in client.get(f"{TRIG}?active_link=true", headers=admin_headers).json] == [T, elsewhere.id]

    disabled = client.patch(f"{PROV}/{git_provider.id}", json={"enabled": False}, headers=admin_headers)
    assert disabled.status_code == 200, disabled.json

    assert active(trigger_links) == [False, True] and active(results_links) == [False]
    assert active_ids(trigger_links) == [elsewhere.id]
    assert [r["id"] for r in client.get(f"{TRIG}?active_link=true", headers=admin_headers).json] == [elsewhere.id]
    # the repositories themselves are still enabled, and say which provider is not
    repo = client.get(f"{TRIG}/{T}", headers=admin_headers).json
    assert repo["enabled"] is True and repo["provider"]["enabled"] is False

    # no pull requests are taken for it, and none of its links can be used
    refused = client.post(f"{TRIG}/{T}/pull_requests", json={"pull_requests": []}, headers=admin_headers)
    assert_error(refused, 400)

    client.patch(f"{PROV}/{git_provider.id}", json={"enabled": True}, headers=admin_headers)
    assert active(trigger_links) == [True, True] and active(results_links) == [True]


# ---------------------------------------------------------------- healthcheck

@pytest.mark.parametrize("type,host,path", [
    ("github", "github.com", ""), ("gitea", "git.example.com", "version"),
])
def test_healthcheck_asks_the_api_without_a_token(client, admin_headers, mocker, make_provider, type, host, path):
    provider = make_provider(host, type=type)
    get = mocker.patch("requests.get", return_value=fake_response(200))
    response = client.get(f"{PROV}/{provider.id}/healthcheck", headers=admin_headers)
    assert response.status_code == 200, response.json
    assert response.json["status"] == "ok" and response.json["id"] == provider.id
    assert get.call_args.args[0] == f"{provider.api_uri}/{path}"
    assert "Authorization" not in get.call_args.kwargs["headers"]


def test_healthcheck_failure_is_reported_in_the_body(client, admin_headers, mocker, git_provider):
    mocker.patch("requests.get", side_effect=requests.ConnectionError("down"))
    response = client.get(f"{PROV}/{git_provider.id}/healthcheck", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["status"] == "unreachable"


def test_healthcheck_unknown_provider_is_404(client, admin_headers):
    assert_error(client.get(f"{PROV}/999/healthcheck", headers=admin_headers), 404)
