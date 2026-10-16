from app.helpers.base_model import db

G = "/global/datasets"


def test_create(client, admin_headers, global_secret):
    response = client.post(
        G, json={"name": "NewDs", "host": "db", "port": 5432, "secret_label": "test-creds"},
        headers=admin_headers
    )
    assert response.status_code == 201
    assert response.json["name"] == "newds"
    assert response.json["enabled"] is True
    assert response.json["secret"]["label"] == "test-creds"


def test_create_refuses_credentials_and_project(client, admin_headers, global_secret):
    body = {"name": "NewDs", "host": "db", "port": 5432, "secret_label": "test-creds"}

    with_credentials = client.post(G, json={**body, "username": "u"}, headers=admin_headers)
    assert with_credentials.status_code == 400

    with_project = client.post(G, json={**body, "project_id": 1}, headers=admin_headers)
    assert with_project.status_code == 400


def test_create_needs_secret_label(client, admin_headers):
    response = client.post(
        G, json={"name": "X", "host": "db", "port": 5432}, headers=admin_headers
    )
    assert response.status_code == 400


def test_list_and_get(client, admin_headers, global_dataset):
    listing = client.get(G, headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json["total"] == 1
    assert listing.json["items"][0]["id"] == global_dataset.id

    one = client.get(f"{G}/{global_dataset.id}", headers=admin_headers)
    assert one.status_code == 200
    assert one.json["name"] == "globalds"

    missing = client.get(f"{G}/999", headers=admin_headers)
    assert missing.status_code == 404


def test_patch_needs_lock(client, admin_headers, linked_dataset):
    url = f"{G}/{linked_dataset['dataset']['id']}"

    response = client.patch(url, json={"host": "new"}, headers=admin_headers)
    assert response.status_code == 409


def test_patch_and_delete_when_locked(client, admin_headers, linked_dataset, lock_project):
    url = f"{G}/{linked_dataset['dataset']['id']}"

    patch = client.patch(url, json={"host": "new"}, headers=admin_headers)
    assert patch.status_code == 202
    assert patch.json["host"] == "new"

    delete = client.delete(url, headers=admin_headers)
    assert delete.status_code == 204


def test_link_and_list(client, admin_headers, project, global_dataset):
    url = f"/projects/{project.id}/datasets/{global_dataset.id}"

    put = client.put(url, json={}, headers=admin_headers)
    assert put.status_code == 201
    assert put.json["active"] is True
    assert put.json["dataset"]["id"] == global_dataset.id

    listing = client.get(f"/projects/{project.id}/datasets", headers=admin_headers)
    assert listing.status_code == 200
    assert len(listing.json) == 1

    get = client.get(url, headers=admin_headers)
    assert get.status_code == 200


def test_link_errors(client, admin_headers, project, other_project, global_dataset):
    missing = client.put(f"/projects/{project.id}/datasets/999", json={}, headers=admin_headers)
    assert missing.status_code == 404

    bogus = client.put(
        f"/projects/{project.id}/datasets/{global_dataset.id}", json={"bogus": 1}, headers=admin_headers
    )
    assert bogus.status_code == 400

    cross_project = client.get(
        f"/projects/{other_project.id}/datasets/{global_dataset.id}", headers=admin_headers
    )
    assert cross_project.status_code == 404


def test_revoke_admin_only(client, admin_headers, post_json_user_header, linked_dataset):
    url = f"/projects/{linked_dataset['project_id']}/datasets/{linked_dataset['dataset']['id']}"

    denied = client.patch(url, json={"revoked": True}, headers=post_json_user_header)
    assert denied.status_code == 403

    revoked = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert revoked.status_code == 200
    assert revoked.json["active"] is False


def test_disable_link_needs_lock_and_unlink(client, admin_headers, project, linked_dataset):
    url = f"/projects/{project.id}/datasets/{linked_dataset['dataset']['id']}"

    unlocked = client.patch(url, json={"enabled": False}, headers=admin_headers)
    assert unlocked.status_code == 409

    project.locked = True
    db.session.commit()

    locked = client.patch(url, json={"enabled": False}, headers=admin_headers)
    assert locked.status_code == 200
    assert locked.json["active"] is False

    delete = client.delete(url, headers=admin_headers)
    assert delete.status_code == 204
