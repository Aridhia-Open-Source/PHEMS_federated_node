from app.helpers.base_model import db

G = "/global/secrets"
NEW = {"label": "new-creds", "provider": "K8S", "values": {"TOKEN": "t"}}


def test_create(client, admin_headers, k8s_client):
    response = client.post(G, json=NEW, headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["label"] == "new-creds"
    assert response.json["key"] == "fn-secret-new-creds"
    assert "values" not in response.json
    assert k8s_client["create_namespaced_secret_mock"].called


def test_create_duplicate_conflicts(client, admin_headers, k8s_client):
    response = client.post(G, json=NEW, headers=admin_headers)
    assert response.status_code == 201, response.json

    response = client.post(G, json=NEW, headers=admin_headers)
    assert response.status_code == 409, response.json


def test_create_bad_bodies(client, admin_headers, k8s_client):
    response = client.post(G, json={"label": "x", "provider": "K8S"}, headers=admin_headers)
    assert response.status_code == 400, response.json

    response = client.post(
        G, json={"label": "x", "provider": "NOPE", "values": {"TOKEN": "t"}}, headers=admin_headers
    )
    assert response.status_code == 400, response.json


def test_list_and_get(client, admin_headers, global_secret):
    response = client.get(G, headers=admin_headers)
    assert response.status_code == 200, response.json
    assert [s["label"] for s in response.json] == ["test-creds"]

    response = client.get(f"{G}/test-creds", headers=admin_headers)
    assert response.status_code == 200, response.json

    response = client.get(f"{G}/nope", headers=admin_headers)
    assert response.status_code == 404, response.json


def test_rotate_and_disable(client, admin_headers, k8s_client):
    response = client.post(G, json=NEW, headers=admin_headers)
    assert response.status_code == 201, response.json

    response = client.patch(f"{G}/new-creds", json={"values": {"TOKEN": "t2"}}, headers=admin_headers)
    assert response.status_code == 200, response.json

    response = client.patch(f"{G}/new-creds", json={"enabled": False}, headers=admin_headers)
    assert response.status_code == 200, response.json
    assert response.json["enabled"] is False


def test_delete_in_use_conflicts(client, admin_headers, global_trigger_repo):
    response = client.delete(f"{G}/test-creds", headers=admin_headers)
    assert response.status_code == 409, response.json


def test_delete(client, admin_headers, k8s_client):
    response = client.post(G, json=NEW, headers=admin_headers)
    assert response.status_code == 201, response.json

    response = client.delete(f"{G}/new-creds", headers=admin_headers)
    assert response.status_code == 204, response.json
    assert k8s_client["delete_namespaced_secret_mock"].called

    response = client.get(f"{G}/new-creds", headers=admin_headers)
    assert response.status_code == 404, response.json


def test_link_and_get(client, admin_headers, project, global_secret):
    url = f"/projects/{project.id}/secrets/test-creds"

    response = client.put(url, json={}, headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["active"] is True
    assert response.json["secret"]["label"] == "test-creds"

    response = client.get(url, headers=admin_headers)
    assert response.status_code == 200, response.json

    response = client.get(f"/projects/{project.id}/secrets", headers=admin_headers)
    assert response.status_code == 200, response.json
    assert len(response.json) == 1


def test_link_errors(client, admin_headers, project, other_project, linked_secret):
    response = client.put(f"/projects/{project.id}/secrets/nope", json={}, headers=admin_headers)
    assert response.status_code == 404, response.json

    # Unlocked, so the second PUT (a settings replace) is refused
    response = client.put(f"/projects/{project.id}/secrets/test-creds", json={}, headers=admin_headers)
    assert response.status_code == 409, response.json

    response = client.get(f"/projects/{other_project.id}/secrets/test-creds", headers=admin_headers)
    assert response.status_code == 404, response.json


def test_revoke_and_unlink(client, admin_headers, post_json_user_header, project, linked_secret):
    url = f"/projects/{project.id}/secrets/test-creds"

    response = client.patch(url, json={"revoked": True}, headers=post_json_user_header)
    assert response.status_code == 403, response.json

    response = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert response.status_code == 200, response.json
    assert response.json["active"] is False

    # Unlocked, so unlinking is refused
    response = client.delete(url, headers=admin_headers)
    assert response.status_code == 409, response.json

    project.locked = True
    db.session.commit()

    response = client.delete(url, headers=admin_headers)
    assert response.status_code == 204, response.json
