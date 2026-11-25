"""
Who may write (ADR 0037): the creator's manage grant, a write grant to the user or a group, SuperUser; operate turns
a project on or off; assigning needs both sides; execute runs tasks. The deny for every route is walked in
test_users_and_ownership.py.
"""
from datetime import datetime as dt, timedelta

import pytest

from app.database.base_model import db
from app.models.dataset import Dataset
from app.models.project import Project
from tests.conftest import SYSTEM_TOKEN, claims_for

# token -> a second admin, who holds no grant until a test gives one, and the SuperUser
OTHERS = {
    "other_token": ("id-other", "other", "Administrator", ["/roles/admins", "/studies/uc1"]),
    "super_token": ("id-super", "root", "SuperUser", None),
    "operator_token": ("id-svc", "svc", "Service", None),
}


@pytest.fixture(autouse=True)
def others(token_claims):
    for token, (sub, username, role, groups) in OTHERS.items():
        token_claims[token] = claims_for(sub, username, role, groups)


def as_(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def grant(client, path: str, relation: str, subject_id: str = "id-other", subject_type: str = "user", **extra):
    """The admin, who owns the record, grants the relation on it."""
    body = {"relation": relation, "subject_type": subject_type, "subject_id": subject_id, **extra}
    response = client.post(f"{path}/grants", json=body, headers=as_("admin_token"))
    assert response.status_code == 201, response.json()


def patch_project(client, project, token, body):
    return client.patch(f"/projects/{project.id}", json=body, headers=as_(token))


def test_the_owner_writes_and_another_admin_gets_a_409_naming_the_owner(client, project):
    assert patch_project(client, project, "admin_token", {"enabled": False}).status_code == 200
    response = patch_project(client, project, "other_token", {"enabled": True})
    assert response.status_code == 409
    assert "owned by admin" in response.json()["error"]


@pytest.mark.parametrize("subject_type,subject_id", [("user", "id-other"), ("group", "/studies/uc1")])
def test_a_write_grant_to_the_user_or_its_group_allows_the_write(client, project, subject_type, subject_id):
    grant(client, f"/projects/{project.id}", "write", subject_id, subject_type)
    assert patch_project(client, project, "other_token", {"revoked": True}).status_code == 200


def test_an_expired_grant_allows_nothing(client, project):
    grant(client, f"/projects/{project.id}", "write", expires_at=(dt.utcnow() - timedelta(minutes=1)).isoformat())
    assert patch_project(client, project, "other_token", {"enabled": False}).status_code == 409


def test_the_superuser_writes_without_a_grant(client, project):
    assert patch_project(client, project, "super_token", {"revoked": True}).status_code == 200


def test_operate_turns_the_project_on_or_off_but_does_not_revoke_it(client, project):
    grant(client, f"/projects/{project.id}", "operate")
    assert patch_project(client, project, "other_token", {"enabled": False}).status_code == 200
    assert patch_project(client, project, "other_token", {"revoked": True}).status_code == 409
    db.session.expire_all()
    assert Project.get_by_id(project.id).revoked is False


def test_operate_turns_a_dataset_assignment_on_or_off_but_changes_nothing_else(
    client, project, global_dataset, assigned_dataset,
):
    grant(client, f"/projects/{project.id}", "operate")
    path = f"/projects/{project.id}/datasets/{global_dataset.id}"
    assert client.patch(path, json={"enabled": False}, headers=as_("other_token")).status_code == 200
    assert client.patch(path, json={"revoked": True}, headers=as_("other_token")).status_code == 409


def test_creating_a_global_record_is_for_admins_and_the_operator(client):
    body = {"name": "p", "type": "gitea", "uri": "https://p.example.com", "api_uri": "https://p.example.com/api/v1"}
    assert client.post("/global/providers", json=body, headers=as_(SYSTEM_TOKEN)).status_code == 409
    assert client.post("/global/providers", json=body, headers=as_("operator_token")).status_code == 201


def test_dagster_cannot_write_a_record(client, project):
    assert patch_project(client, project, SYSTEM_TOKEN, {"enabled": False}).status_code == 409


def test_assigning_needs_write_on_the_project_and_assign_on_the_global_record(client, global_dataset):
    """The other admin owns their project; the dataset is admin's. Admins have assign on every global record."""
    project_id = client.post("/projects", json={"name": "theirs"}, headers=as_("other_token")).json()["id"]
    path = f"/projects/{project_id}/datasets/{global_dataset.id}"
    assert client.put(path, json={}, headers=as_("operator_token")).status_code == 409
    assert client.put(path, json={}, headers=as_("other_token")).status_code == 201
    assert client.delete(path, headers=as_("other_token")).status_code == 204


def test_the_operator_needs_an_assign_grant_to_assign_an_admins_record(client, global_dataset):
    project_id = client.post("/projects", json={"name": "ops"}, headers=as_("operator_token")).json()["id"]
    path = f"/projects/{project_id}/datasets/{global_dataset.id}"
    response = client.put(path, json={}, headers=as_("operator_token"))
    assert response.status_code == 409
    assert "owned by admin" in response.json()["error"]

    grant(client, f"/global/datasets/{global_dataset.id}", "assign", "/roles/service", "group")
    assert client.put(path, json={}, headers=as_("operator_token")).status_code == 201


def test_running_a_task_needs_execute_on_the_project(client, project, mocker):
    mocker.patch("app.tasks_api.Task.validate", return_value={"dataset": None})
    response = client.post(f"/projects/{project.id}/tasks", json={}, headers=as_("other_token"))
    assert response.status_code == 409
    assert "execute" in response.json()["error"]


def test_retrying_or_cancelling_a_task_needs_execute_on_the_project_not_write(client, project):
    url = f"/projects/{project.id}/tasks/999"
    grant(client, f"/projects/{project.id}", "write")
    assert client.post(f"{url}/retry", json={}, headers=as_("other_token")).status_code == 409
    assert client.post(f"{url}/cancel", json={}, headers=as_("other_token")).status_code == 409
    grant(client, f"/projects/{project.id}", "execute")
    assert client.post(f"{url}/retry", json={}, headers=as_("other_token")).status_code == 404
    assert client.post(f"{url}/cancel", json={}, headers=as_("other_token")).status_code != 409


def test_nobody_runs_a_task_on_a_revoked_dataset_not_even_the_superuser(client, enabled_project, global_dataset, mocker):
    Dataset.get_by_id(global_dataset.id).revoked = True
    db.session.commit()
    mocker.patch("app.tasks_api.Task.validate", return_value={"dataset": Dataset.get_by_id(global_dataset.id)})
    mocker.patch("app.tasks_api.TaskSpecRequest.from_api_body")
    response = client.post(f"/projects/{enabled_project.id}/tasks", json={}, headers=as_("super_token"))
    assert response.status_code == 409
    assert "execute" in response.json()["error"]
