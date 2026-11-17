"""
Records the nexus operator manages (ADR 0032, helpers/managed.py): its calls mark them, anyone else's change to a
declared field or removal is a 409, and runtime state (revoked, a global resource's enabled) stays editable.
"""
from copy import deepcopy

import pytest

from app.helpers.base_model import db

OPERATOR_TOKEN = "operator_token"


@pytest.fixture
def operator_headers(mock_kc_client, basic_user):
    """The operator's bearer token: an admin whose token names the fn-operator user."""
    kc = mock_kc_client["wrappers_kc"].return_value
    user, operator = deepcopy(basic_user), {**basic_user, "username": "fn-operator"}
    kc.decode_token.side_effect = lambda token: operator if token == OPERATOR_TOKEN else user
    kc.is_user_admin.side_effect = lambda token: token in ("admin_token", OPERATOR_TOKEN)
    is_valid = kc.is_token_valid.side_effect
    kc.is_token_valid.side_effect = lambda token, *args, **kwargs: token == OPERATOR_TOKEN or is_valid(token, *args, **kwargs)
    return {"Content-Type": "application/json", "Authorization": f"Bearer {OPERATOR_TOKEN}"}


@pytest.fixture
def managed_project(project):
    project.managed_by = "fn-operator"
    db.session.commit()
    return project


def body(**fields):
    return {
        "name": "github", "type": "github", "uri": "https://github.com", "api_uri": "https://api.github.com", **fields
    }


def assert_conflict(response):
    assert response.status_code == 409, response.json()
    assert "custom resource" in response.json()["error"]


def test_operator_create_marks_the_record_and_others_get_a_409(client, operator_headers, admin_headers):
    created = client.post("/global/providers", json=body(), headers=operator_headers)
    assert created.status_code == 201, created.json()
    assert created.json()["managed_by"] == "fn-operator"
    provider = f"/global/providers/{created.json()['id']}"

    assert_conflict(client.patch(provider, json={"name": "renamed"}, headers=admin_headers))
    assert_conflict(client.delete(provider, headers=admin_headers))
    # Runtime state stays editable
    assert client.patch(provider, json={"enabled": False}, headers=admin_headers).status_code == 200
    assert client.patch(provider, json={"revoked": True}, headers=admin_headers).status_code == 200
    # The operator may change what it declares
    assert client.patch(provider, json={"name": "renamed"}, headers=operator_headers).status_code == 200


def test_a_record_made_by_hand_is_editable_until_the_operator_adopts_it(client, operator_headers, admin_headers):
    created = client.post("/global/providers", json=body(), headers=admin_headers)
    assert created.json()["managed_by"] is None
    provider = f"/global/providers/{created.json()['id']}"
    assert client.patch(provider, json={"name": "by-hand"}, headers=admin_headers).status_code == 200

    adopted = client.patch(provider, json=body(), headers=operator_headers)
    assert adopted.json()["managed_by"] == "fn-operator"
    assert_conflict(client.patch(provider, json={"name": "by-hand"}, headers=admin_headers))


def test_managed_secret_values_refused_but_not_by_the_operator(client, operator_headers, admin_headers, global_secret):
    global_secret.managed_by = "fn-operator"
    db.session.commit()
    assert_conflict(client.patch(f"/global/secrets/{global_secret.label}", json={"values": {"A": "b"}}, headers=admin_headers))
    assert_conflict(client.delete(f"/global/secrets/{global_secret.label}", headers=admin_headers))


def test_managed_dataset_fields_refused(client, admin_headers, global_dataset):
    global_dataset.managed_by = "fn-operator"
    db.session.commit()
    assert_conflict(client.patch(f"/global/datasets/{global_dataset.id}", json={"host": "elsewhere"}, headers=admin_headers))
    assert client.patch(f"/global/datasets/{global_dataset.id}", json={"revoked": True}, headers=admin_headers).status_code == 200


def test_managed_repository_secret_refused(client, admin_headers, global_trigger_repo, global_results_repo, global_secret):
    for path, repo in (("triggers", global_trigger_repo), ("results", global_results_repo)):
        repo.managed_by = "fn-operator"
        db.session.commit()
        url = f"/global/repositories/{path}/{repo.id}"
        assert_conflict(client.patch(url, json={"secret_label": global_secret.label}, headers=admin_headers))
        assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 200


def test_managed_project_and_its_assignments(
    client, admin_headers, assigned_trigger_repo, assigned_results_repo, managed_project, global_dataset,
):
    project = f"/projects/{managed_project.id}"
    trigger = f"{project}/repositories/triggers/{assigned_trigger_repo['trigger_repository']['id']}"
    results = f"{project}/repositories/results/{assigned_results_repo['results_repository']['id']}"

    assert client.get(project, headers=admin_headers).json()["managed_by"] == "fn-operator"
    assert_conflict(client.patch(project, json={"enabled": False}, headers=admin_headers))
    assert_conflict(client.patch(trigger, json={"enabled": False}, headers=admin_headers))
    assert_conflict(client.patch(results, json={"target_dir": "elsewhere"}, headers=admin_headers))
    assert_conflict(client.delete(trigger, headers=admin_headers))
    assert_conflict(client.put(f"{project}/datasets/{global_dataset.id}", json={}, headers=admin_headers))
    assert_conflict(client.delete(project, headers=admin_headers))
    # Revoking is the admin's switch, and stays editable
    assert client.patch(project, json={"revoked": True}, headers=admin_headers).status_code == 200
    assert client.patch(trigger, json={"revoked": True}, headers=admin_headers).status_code == 200
    assert client.patch(results, json={"revoked": True}, headers=admin_headers).status_code == 200
