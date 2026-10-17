"""/projects API: CRUD, enabled/locked semantics, link gating (datasets, secrets), delete cascade."""
import pytest

from app.helpers.base_model import db


def create(client, admin_headers, **body):
    return client.post("/projects", json=body, headers=admin_headers)


def patch(client, admin_headers, pid, **body):
    return client.patch(f"/projects/{pid}", json=body, headers=admin_headers)


def refresh(obj):
    db.session.expire_all()
    return obj


# ---------------------------------------------------------------- create / get

def test_create_and_get_shape_defaults(client, admin_headers):
    created = create(client, admin_headers, name="Alpha", description="first")
    assert created.status_code == 201, created.json
    assert set(created.json) == {"id"}
    got = client.get(f"/projects/{created.json['id']}", headers=admin_headers).json
    assert set(got) == {"id", "name", "description", "enabled", "locked", "default_dataset_id",
                        "created_at", "updated_at"}
    assert (got["name"], got["description"], got["enabled"], got["locked"], got["default_dataset_id"]) == \
        ("Alpha", "first", False, True, None)
    plain = create(client, admin_headers, name="Plain", enabled=True)
    plain_json = client.get(f"/projects/{plain.json['id']}", headers=admin_headers).json
    assert plain_json["description"] is None and plain_json["enabled"] is True and plain_json["locked"] is True


def test_create_cannot_set_locked(client, admin_headers):
    response = create(client, admin_headers, name="Sneaky", locked=True)  # accepted but ignored
    assert response.status_code == 201, response.json
    assert client.get(f"/projects/{response.json['id']}", headers=admin_headers).json["locked"] is True


def test_create_duplicate_name_is_409(client, admin_headers, project):
    response = create(client, admin_headers, name=project.name)
    assert response.status_code == 409 and "error" in response.json


@pytest.mark.parametrize("body", [
    {}, {"name": None}, {"name": ""}, {"name": "   "},  # missing, null, blank
    {"name": 123}, {"name": "x" * 300},  # non-string, overlong: 400 and never 500
    {"name": "Bad", "enabled": "yes"},
])
def test_create_invalid_is_400(client, admin_headers, body):
    assert create(client, admin_headers, **body).status_code == 400


def test_unknown_project_and_non_integer_id_are_404(client, admin_headers, global_secret):
    for pid in (9999, "abc"):
        for method, body in (("get", None), ("delete", None), ("patch", {"locked": True})):
            response = getattr(client, method)(f"/projects/{pid}", json=body, headers=admin_headers)
            assert response.status_code == 404 and "error" in response.json
    assert client.put("/projects/9999/secrets/test-creds", json={}, headers=admin_headers).status_code == 404
    assert client.get("/projects/9999/secrets", headers=admin_headers).status_code == 404


# ---------------------------------------------------------------- patch

@pytest.mark.parametrize("body", [
    {}, {"bogus": True}, {"name": "renamed"}, {"locked": True, "name": "x"},  # empty/unknown fields refused
    {"enabled": "true"}, {"locked": 1}, {"locked": None},
])
def test_patch_invalid_is_400_and_changes_nothing(client, admin_headers, project, body):
    response = client.patch(f"/projects/{project.id}", json=body, headers=admin_headers)
    assert response.status_code == 400 and "error" in response.json
    assert refresh(project).locked is False


def test_lock_and_unlock_always_allowed_even_with_tasks(client, admin_headers, project, make_task):
    make_task()
    for locked in (True, True, False):  # includes idempotent lock
        response = patch(client, admin_headers, project.id, locked=locked)
        assert response.status_code == 200 and response.json["locked"] is locked
        assert client.get(f"/projects/{project.id}", headers=admin_headers).json["locked"] is locked


def test_enable_and_disable_need_lock(client, admin_headers, lock_project):
    unlocked_fresh = client.post("/projects", json={"name": "Fresh"}, headers=admin_headers).json["id"]
    assert patch(client, admin_headers, unlocked_fresh, locked=False).status_code == 200  # new projects start locked
    assert patch(client, admin_headers, unlocked_fresh, enabled=True).status_code == 409
    # the drain guard sees the state before the patch, so locking in the same call does not help
    assert patch(client, admin_headers, unlocked_fresh, enabled=True, locked=True).status_code == 409
    assert patch(client, admin_headers, lock_project.id, enabled=True).status_code == 200
    # enabled + unlock together is fine once locked
    both = patch(client, admin_headers, lock_project.id, enabled=False, locked=False)
    assert both.status_code == 200 and both.json["enabled"] is False and both.json["locked"] is False
    assert patch(client, admin_headers, lock_project.id, enabled=False).status_code == 409


def test_enable_and_disable_blocked_by_task_in_flight(client, admin_headers, lock_project, make_task):
    task = make_task()
    blocked = patch(client, admin_headers, lock_project.id, enabled=True, locked=False)
    assert blocked.status_code == 409 and blocked.json["details"] == [task.id]
    refresh(lock_project)
    assert lock_project.locked is True and lock_project.enabled is False  # failed patch changes nothing
    task.status = "FAILED"
    db.session.commit()
    assert patch(client, admin_headers, lock_project.id, enabled=True).status_code == 200
    make_task()
    assert patch(client, admin_headers, lock_project.id, enabled=False).status_code == 409
    assert refresh(lock_project).enabled is True


def test_disable_keeps_links_but_drops_out_of_active_link_filter(
        client, admin_headers, enabled_project, linked_trigger_repo, linked_secret, linked_dataset,
        global_trigger_repo):
    pid = enabled_project.id
    enabled_project.locked = True
    db.session.commit()
    assert patch(client, admin_headers, pid, enabled=False).status_code == 200
    triggers = client.get(f"/projects/{pid}/repositories/triggers", headers=admin_headers).json
    assert triggers[0]["trigger_repository"]["id"] == global_trigger_repo.id
    assert len(client.get(f"/projects/{pid}/secrets", headers=admin_headers).json) == 1
    assert len(client.get(f"/projects/{pid}/datasets", headers=admin_headers).json) == 1
    assert client.get("/global/repositories/triggers?active_link=true", headers=admin_headers).json == []


# ---------------------------------------------------------------- secret links

def test_secret_link_get_list_and_errors(client, admin_headers, project, other_project, global_secret):
    url = f"/projects/{project.id}/secrets/test-creds"
    linked = client.put(url, json={}, headers=admin_headers)
    assert linked.status_code == 201, linked.json
    assert linked.json["active"] is True and linked.json["secret"]["label"] == "test-creds"
    assert client.get(url, headers=admin_headers).status_code == 200
    assert len(client.get(f"/projects/{project.id}/secrets", headers=admin_headers).json) == 1
    assert client.put(f"/projects/{project.id}/secrets/nope", json={}, headers=admin_headers).status_code == 404
    # unlocked, so a second PUT (a settings replace) is refused
    assert client.put(url, json={}, headers=admin_headers).status_code == 409
    assert client.get(f"/projects/{other_project.id}/secrets/test-creds", headers=admin_headers).status_code == 404


def test_link_changes_are_gated_by_project_lock_and_tasks(client, admin_headers, project, linked_secret, make_task):
    url = f"/projects/{project.id}/secrets/test-creds"
    # revoke is never gated, the other changes need the lock
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 409
    assert client.delete(url, headers=admin_headers).status_code == 409
    revoked = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert revoked.status_code == 200 and revoked.json["active"] is False
    assert patch(client, admin_headers, project.id, locked=True).status_code == 200
    task = make_task()
    in_flight = client.delete(url, headers=admin_headers)  # a task in flight blocks even when locked
    assert in_flight.status_code == 409 and in_flight.json["details"] == [task.id]
    task.status = "FAILED"
    db.session.commit()
    assert client.put(url, json={"enabled": False}, headers=admin_headers).status_code == 200
    assert patch(client, admin_headers, project.id, locked=False).status_code == 200
    assert client.patch(url, json={"enabled": True}, headers=admin_headers).status_code == 409  # unlocking restores gating
    patch(client, admin_headers, project.id, locked=True)
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).status_code == 404


def test_first_trigger_link_needs_no_lock(client, admin_headers, project, global_trigger_repo):
    response = client.put(f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}",
                          json={"watch_dir": "triggers"}, headers=admin_headers)
    assert project.enabled is False and response.status_code == 201


# ---------------------------------------------------------------- dataset links and default dataset

def test_dataset_link_get_list_and_errors(client, admin_headers, project, other_project, global_dataset):
    url = f"/projects/{project.id}/datasets/{global_dataset.id}"
    linked = client.put(url, json={}, headers=admin_headers)
    assert linked.status_code == 201, linked.json
    assert linked.json["active"] is True and linked.json["dataset"]["id"] == global_dataset.id
    assert client.get(url, headers=admin_headers).status_code == 200
    assert len(client.get(f"/projects/{project.id}/datasets", headers=admin_headers).json) == 1
    assert client.put(f"/projects/{project.id}/datasets/999", json={}, headers=admin_headers).status_code == 404
    assert client.put(url + "x", json={}, headers=admin_headers).status_code == 404
    assert client.put(f"/projects/{other_project.id}/datasets/{global_dataset.id}", json={"bogus": 1},
                      headers=admin_headers).status_code == 400
    assert client.get(f"/projects/{other_project.id}/datasets/{global_dataset.id}",
                      headers=admin_headers).status_code == 404


def test_dataset_link_disable_unlink_and_default_dataset(
        client, admin_headers, project, linked_dataset, global_dataset):
    url = f"/projects/{project.id}/datasets/{global_dataset.id}"
    assert client.get(f"/projects/{project.id}", headers=admin_headers).json["default_dataset_id"] == global_dataset.id
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 409  # needs lock
    patch(client, admin_headers, project.id, locked=True)
    disabled = client.patch(url, json={"enabled": False}, headers=admin_headers)
    assert disabled.status_code == 200 and disabled.json["active"] is False
    assert client.delete(url, headers=admin_headers).status_code == 204
    # unlinking the default dataset clears the project default
    assert client.get(f"/projects/{project.id}", headers=admin_headers).json["default_dataset_id"] is None


# ---------------------------------------------------------------- delete

def test_delete_needs_lock_then_removes_project_and_frees_name(client, admin_headers, project, other_project):
    assert client.delete(f"/projects/{project.id}", headers=admin_headers).status_code == 409
    assert client.get(f"/projects/{project.id}", headers=admin_headers).status_code == 200
    patch(client, admin_headers, project.id, locked=True)
    deleted = client.delete(f"/projects/{project.id}", headers=admin_headers)
    assert deleted.status_code == 204 and deleted.data == b""
    assert client.delete(f"/projects/{project.id}", headers=admin_headers).status_code == 404
    assert client.get(f"/projects/{other_project.id}", headers=admin_headers).status_code == 200
    assert client.get("/projects", headers=admin_headers).json["total"] == 1
    assert create(client, admin_headers, name=project.name).status_code == 201


def test_delete_blocked_by_task_in_flight(client, admin_headers, lock_project, make_task):
    task = make_task()
    response = client.delete(f"/projects/{lock_project.id}", headers=admin_headers)
    assert response.status_code == 409 and response.json["details"] == [task.id]
    assert client.get(f"/projects/{lock_project.id}", headers=admin_headers).status_code == 200


def test_delete_cascades_links_but_keeps_global_resources(
        client, admin_headers, k8s_client, project, other_project, linked_secret, linked_dataset,
        linked_trigger_repo, linked_results_repo, global_secret, global_dataset, global_trigger_repo):
    assert client.put(f"/projects/{other_project.id}/secrets/test-creds", json={}, headers=admin_headers).status_code == 201
    assert client.delete("/global/secrets/test-creds", headers=admin_headers).status_code == 409
    project.locked = True
    db.session.commit()
    assert client.delete(f"/projects/{project.id}", headers=admin_headers).status_code == 204
    assert client.get(f"/projects/{project.id}/secrets", headers=admin_headers).status_code == 404
    # global resources (incl. the project's default dataset) survive; other projects keep their links
    assert client.get(f"/global/datasets/{global_dataset.id}", headers=admin_headers).status_code == 200
    assert client.get(f"/global/repositories/triggers/{global_trigger_repo.id}", headers=admin_headers).status_code == 200
    assert client.get(f"/projects/{other_project.id}/secrets/test-creds", headers=admin_headers).status_code == 200
    # the dataset and trigger repo are free again, the secret still used by the other project
    assert client.delete(f"/global/datasets/{global_dataset.id}", headers=admin_headers).status_code == 204


def test_delete_removes_tasks_and_project_prs_but_keeps_global_prs(
        client, admin_headers, lock_project, pr_trigger, global_trigger_repo, make_task, spec_raw):
    tid = make_task(status="FAILED").id
    yielded = client.post(pr_trigger + "/task", json={"spec_raw": spec_raw}, headers=admin_headers)  # task from a PR
    assert yielded.status_code == 201, yielded.json
    client.patch(f"/projects/{lock_project.id}/tasks/{yielded.json['id']}", json={"status": "FAILED"}, headers=admin_headers)
    assert client.delete(f"/projects/{lock_project.id}", headers=admin_headers).status_code == 204
    assert client.get(f"/projects/{lock_project.id}/tasks/{tid}", headers=admin_headers).status_code == 404
    assert client.get(f"/projects/{lock_project.id}/tasks/{yielded.json['id']}", headers=admin_headers).status_code == 404
    assert client.get(pr_trigger, headers=admin_headers).status_code == 404
    glob = client.get(f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests", headers=admin_headers)
    assert glob.status_code == 200 and glob.json["total"] == 1
