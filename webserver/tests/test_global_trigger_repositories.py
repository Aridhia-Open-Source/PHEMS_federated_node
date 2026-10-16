import pytest

BASE = "/global/repositories/triggers"


def test_create(client, admin_headers, global_secret):
    body = {"uri": "github.com/org/new", "provider": "github", "secret_label": "test-creds"}

    response = client.post(BASE, json=body, headers=admin_headers)

    assert response.status_code == 201
    assert response.json["uri"] == "github.com/org/new"
    assert response.json["api_uri"] == "https://api.github.com"
    assert response.json["enabled"] is True
    assert response.json["secret"]["label"] == "test-creds"


def test_create_duplicate_uri_conflicts(client, admin_headers, global_secret):
    body = {"uri": "github.com/org/new", "provider": "github", "secret_label": "test-creds"}
    first = client.post(BASE, json=body, headers=admin_headers)
    assert first.status_code == 201

    body["uri"] = "https://github.com/org/new"
    second = client.post(BASE, json=body, headers=admin_headers)

    assert second.status_code == 409


def test_create_unknown_secret(client, admin_headers, global_secret):
    body = {"uri": "github.com/org/new", "provider": "github", "secret_label": "nope"}

    response = client.post(BASE, json=body, headers=admin_headers)

    assert response.status_code == 400


def test_create_bad_provider(client, admin_headers):
    body = {"uri": "github.com/org/new", "provider": "bogus", "secret_label": "test-creds"}

    response = client.post(BASE, json=body, headers=admin_headers)

    assert response.status_code == 400


def test_create_refuses_watch_dir(client, admin_headers):
    body = {
        "uri": "github.com/org/new",
        "provider": "github",
        "secret_label": "test-creds",
        "watch_dir": "x",
    }

    response = client.post(BASE, json=body, headers=admin_headers)

    assert response.status_code == 400


def test_get_one_and_404(client, admin_headers, global_trigger_repo):
    T = global_trigger_repo.id

    response = client.get(f"{BASE}/{T}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["id"] == T

    missing = client.get(f"{BASE}/999", headers=admin_headers)
    assert missing.status_code == 404


def test_list_active_link_filter(
    client,
    admin_headers,
    enabled_project,
    linked_trigger_repo,
    make_trigger_repo,
):
    T = linked_trigger_repo["trigger_repository"]["id"]
    unlinked = make_trigger_repo(uri="github.com/org/unlinked")

    everything = client.get(BASE, headers=admin_headers)
    assert everything.status_code == 200
    assert [item["id"] for item in everything.json] == [T, unlinked.id]

    active = client.get(f"{BASE}?active_link=true", headers=admin_headers)
    assert active.status_code == 200
    assert [item["id"] for item in active.json] == [T]


def test_active_link_excludes_revoked_link(
    client,
    admin_headers,
    enabled_project,
    linked_trigger_repo,
):
    T = linked_trigger_repo["trigger_repository"]["id"]
    link_url = f"/projects/{enabled_project.id}/repositories/triggers/{T}"

    revoke = client.patch(link_url, json={"revoked": True}, headers=admin_headers)
    assert revoke.status_code == 200

    active = client.get(f"{BASE}?active_link=true", headers=admin_headers)
    assert active.status_code == 200
    assert active.json == []


def test_patch_needs_lock_unless_secret_only(client, admin_headers, linked_trigger_repo):
    T = linked_trigger_repo["trigger_repository"]["id"]

    locked_field = client.patch(f"{BASE}/{T}", json={"enabled": False}, headers=admin_headers)
    assert locked_field.status_code == 409

    secret_only = client.patch(
        f"{BASE}/{T}", json={"secret_label": "test-creds"}, headers=admin_headers
    )
    assert secret_only.status_code == 200


def test_disable_and_delete_when_locked(
    client,
    admin_headers,
    linked_trigger_repo,
    lock_project,
):
    T = linked_trigger_repo["trigger_repository"]["id"]

    disable = client.patch(f"{BASE}/{T}", json={"enabled": False}, headers=admin_headers)
    assert disable.status_code == 200
    assert disable.json["enabled"] is False

    delete = client.delete(f"{BASE}/{T}", json={}, headers=admin_headers)
    assert delete.status_code == 204

    gone = client.get(f"{BASE}/{T}", headers=admin_headers)
    assert gone.status_code == 404
