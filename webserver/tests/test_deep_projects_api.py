"""Deep tests of the /projects API: CRUD, enabled/locked semantics, delete cascade, link gating."""
import pytest

from app.helpers.base_model import db
from app.models.project import Project


def _create(client, admin_headers, **body):
    return client.post("/projects", json=body, headers=admin_headers)


def _patch(client, admin_headers, pid, **body):
    return client.patch(f"/projects/{pid}", json=body, headers=admin_headers)


def _refresh(obj):
    db.session.expire_all()
    return obj


# ---------- create ----------

def test_create_returns_201_with_id_and_get_shape(client, admin_headers):
    r = _create(client, admin_headers, name="Alpha", description="first")
    assert r.status_code == 201, r.json
    assert set(r.json) == {"id"}
    got = client.get(f"/projects/{r.json['id']}", headers=admin_headers)
    assert got.status_code == 200
    assert set(got.json) == {
        "id", "name", "description", "enabled", "locked", "default_dataset_id", "created_at", "updated_at"
    }
    assert got.json["name"] == "Alpha"
    assert got.json["description"] == "first"
    assert got.json["enabled"] is False
    assert got.json["locked"] is False
    assert got.json["default_dataset_id"] is None


def test_create_without_description_gives_null(client, admin_headers):
    r = _create(client, admin_headers, name="NoDesc")
    assert r.status_code == 201, r.json
    assert client.get(f"/projects/{r.json['id']}", headers=admin_headers).json["description"] is None


def test_create_enabled_true_is_honoured(client, admin_headers):
    r = _create(client, admin_headers, name="On", enabled=True)
    assert r.status_code == 201, r.json
    got = client.get(f"/projects/{r.json['id']}", headers=admin_headers).json
    assert got["enabled"] is True
    assert got["locked"] is False


def test_create_cannot_set_locked(client, admin_headers):
    r = _create(client, admin_headers, name="Sneaky", locked=True)
    if r.status_code == 201:
        got = client.get(f"/projects/{r.json['id']}", headers=admin_headers).json
        assert got["locked"] is False
    else:
        assert r.status_code == 400


def test_create_duplicate_name_conflicts(client, admin_headers, project):
    r = _create(client, admin_headers, name=project.name)
    assert r.status_code == 409
    assert "error" in r.json
    assert Project.query.filter_by(name=project.name).count() == 1


@pytest.mark.parametrize("body", [{}, {"description": "x"}, {"name": None}])
def test_create_missing_or_null_name_is_400(client, admin_headers, body):
    assert _create(client, admin_headers, **body).status_code == 400


def test_create_enabled_must_be_boolean(client, admin_headers):
    assert _create(client, admin_headers, name="Bad", enabled="yes").status_code == 400
    assert Project.query.filter_by(name="Bad").count() == 0


@pytest.mark.parametrize("name", ["", "   "])
def test_create_blank_name_is_rejected(client, admin_headers, name):
    r = _create(client, admin_headers, name=name)
    assert r.status_code == 400, r.json


def test_create_overlong_name_is_400_not_500(client, admin_headers):
    r = _create(client, admin_headers, name="x" * 300)
    assert r.status_code == 400, r.json


def test_create_non_string_name_is_400_not_500(client, admin_headers):
    r = _create(client, admin_headers, name=123)
    assert r.status_code == 400, r.json


def test_create_name_uniqueness_is_case_sensitive_or_conflicts_never_500(client, admin_headers, project):
    r = _create(client, admin_headers, name=project.name.lower())
    assert r.status_code in (201, 409)


def test_trailing_slash_routes_work(client, admin_headers):
    r = client.post("/projects/", json={"name": "Slash"}, headers=admin_headers)
    assert r.status_code == 201, r.json
    assert client.get("/projects/", headers=admin_headers).status_code == 200


# ---------- get / list ----------

def test_get_unknown_project_404(client, admin_headers):
    r = client.get("/projects/9999", headers=admin_headers)
    assert r.status_code == 404
    assert "error" in r.json


def test_get_non_integer_id_404(client, admin_headers):
    assert client.get("/projects/abc", headers=admin_headers).status_code == 404


def test_list_shape_and_pagination(client, admin_headers, project, other_project):
    r = client.get("/projects", headers=admin_headers)
    assert r.status_code == 200
    assert set(r.json) >= {"items", "page", "per_page", "total", "pages"}
    assert r.json["total"] == 2
    assert {i["name"] for i in r.json["items"]} == {project.name, other_project.name}

    page1 = client.get("/projects?per_page=1&page=1", headers=admin_headers).json
    page2 = client.get("/projects?per_page=1&page=2", headers=admin_headers).json
    assert page1["total"] == 2 and page1["pages"] == 2 and len(page1["items"]) == 1
    assert len(page2["items"]) == 1
    assert page1["items"][0]["id"] != page2["items"][0]["id"]
    beyond = client.get("/projects?per_page=1&page=3", headers=admin_headers)
    assert beyond.status_code in (200, 404)
    if beyond.status_code == 200:
        assert beyond.json["items"] == []


def test_list_empty(client, admin_headers):
    r = client.get("/projects", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["items"] == [] and r.json["total"] == 0


def test_list_filters_by_name_enabled_and_locked(client, admin_headers, project, other_project):
    other_project.enabled = True
    project.locked = True
    db.session.commit()
    by_name = client.get(f"/projects?name={project.name}", headers=admin_headers).json
    assert [i["id"] for i in by_name["items"]] == [project.id]
    enabled = client.get("/projects?enabled=true", headers=admin_headers)
    assert enabled.status_code == 200
    assert [i["id"] for i in enabled.json["items"]] == [other_project.id]
    locked = client.get("/projects?locked=true", headers=admin_headers)
    assert [i["id"] for i in locked.json["items"]] == [project.id]
    ne = client.get(f"/projects?name__ne={project.name}", headers=admin_headers)
    assert [i["id"] for i in ne.json["items"]] == [other_project.id]


def test_list_bad_filter_or_paging_is_400(client, admin_headers, project):
    assert client.get("/projects?nonsense=1", headers=admin_headers).status_code == 400
    assert client.get("/projects?page=abc", headers=admin_headers).status_code == 400


# ---------- patch: validation ----------

def test_patch_unknown_project_404(client, admin_headers):
    assert _patch(client, admin_headers, 9999, locked=True).status_code == 404


@pytest.mark.parametrize("body", [{}, {"name": "renamed"}, {"locked": True, "name": "x"}, {"bogus": True}])
def test_patch_empty_or_unknown_fields_400(client, admin_headers, project, body):
    r = client.patch(f"/projects/{project.id}", json=body, headers=admin_headers)
    assert r.status_code == 400, r.json
    assert "error" in r.json
    assert _refresh(project).locked is False


@pytest.mark.parametrize("field", ["enabled", "locked"])
@pytest.mark.parametrize("value", ["true", 1, None])
def test_patch_non_boolean_400(client, admin_headers, project, field, value):
    r = client.patch(f"/projects/{project.id}", json={field: value}, headers=admin_headers)
    assert r.status_code == 400, r.json


# ---------- patch: locked / enabled semantics ----------

def test_lock_and_unlock_are_always_allowed(client, admin_headers, project):
    r = _patch(client, admin_headers, project.id, locked=True)
    assert r.status_code == 200 and r.json["locked"] is True
    assert client.get(f"/projects/{project.id}", headers=admin_headers).json["locked"] is True
    r = _patch(client, admin_headers, project.id, locked=False)
    assert r.status_code == 200 and r.json["locked"] is False


def test_lock_is_idempotent(client, admin_headers, lock_project):
    r = _patch(client, admin_headers, lock_project.id, locked=True)
    assert r.status_code == 200 and r.json["locked"] is True


def test_lock_with_tasks_in_flight_is_allowed(client, admin_headers, project, make_task):
    make_task()
    r = _patch(client, admin_headers, project.id, locked=True)
    assert r.status_code == 200 and r.json["locked"] is True


def test_unlock_with_tasks_in_flight_is_allowed(client, admin_headers, lock_project, make_task):
    make_task()
    r = _patch(client, admin_headers, lock_project.id, locked=False)
    assert r.status_code == 200 and r.json["locked"] is False


def test_enable_requires_lock(client, admin_headers, project):
    r = _patch(client, admin_headers, project.id, enabled=True)
    assert r.status_code == 409
    assert _refresh(project).enabled is False


def test_enable_when_locked_and_drained(client, admin_headers, lock_project):
    r = _patch(client, admin_headers, lock_project.id, enabled=True)
    assert r.status_code == 200
    assert r.json["enabled"] is True and r.json["locked"] is True


def test_enable_project_with_no_links_succeeds(client, admin_headers, lock_project):
    assert client.get(f"/projects/{lock_project.id}/repositories/triggers", headers=admin_headers).json == []
    assert _patch(client, admin_headers, lock_project.id, enabled=True).status_code == 200


def test_enable_blocked_by_task_in_flight_lists_task_ids(client, admin_headers, lock_project, make_task):
    task = make_task()
    r = _patch(client, admin_headers, lock_project.id, enabled=True)
    assert r.status_code == 409
    assert r.json["details"] == [task.id]
    assert _refresh(lock_project).enabled is False


def test_disable_blocked_by_task_in_flight(client, admin_headers, enabled_project, make_task):
    enabled_project.locked = True
    db.session.commit()
    make_task()
    r = _patch(client, admin_headers, enabled_project.id, enabled=False)
    assert r.status_code == 409
    assert _refresh(enabled_project).enabled is True


def test_disable_when_unlocked_is_409(client, admin_headers, enabled_project):
    assert _patch(client, admin_headers, enabled_project.id, enabled=False).status_code == 409


def test_patch_enabled_and_locked_together_enable_and_unlock(client, admin_headers, lock_project):
    r = _patch(client, admin_headers, lock_project.id, enabled=True, locked=False)
    assert r.status_code == 200
    assert r.json["enabled"] is True and r.json["locked"] is False


def test_patch_enabled_and_locked_together_needs_prior_lock(client, admin_headers, project):
    # The drain guard runs against the state before the patch, so locking in the same call does not help.
    r = _patch(client, admin_headers, project.id, enabled=True, locked=True)
    assert r.status_code == 409
    assert _refresh(project).locked is False and project.enabled is False


def test_failed_patch_changes_nothing(client, admin_headers, lock_project, make_task):
    make_task()
    r = _patch(client, admin_headers, lock_project.id, enabled=True, locked=False)
    assert r.status_code == 409
    _refresh(lock_project)
    assert lock_project.locked is True and lock_project.enabled is False


def test_enable_ready_after_task_finishes(client, admin_headers, lock_project, make_task):
    task = make_task()
    assert _patch(client, admin_headers, lock_project.id, enabled=True).status_code == 409
    task.status = "FAILED"
    db.session.commit()
    assert _patch(client, admin_headers, lock_project.id, enabled=True).status_code == 200


def test_disable_project_with_linked_resources_keeps_links(
    client, admin_headers, enabled_project, linked_trigger_repo, linked_secret, linked_dataset, global_trigger_repo
):
    pid = enabled_project.id
    enabled_project.locked = True
    db.session.commit()
    assert _patch(client, admin_headers, pid, enabled=False).status_code == 200
    assert client.get(f"/projects/{pid}/repositories/triggers", headers=admin_headers).json[0]["trigger_repository"]["id"] == global_trigger_repo.id
    assert len(client.get(f"/projects/{pid}/secrets", headers=admin_headers).json) == 1
    assert len(client.get(f"/projects/{pid}/datasets", headers=admin_headers).json) == 1
    # disabled project no longer shows up in the ingest filter
    active = client.get("/global/repositories/triggers?active_link=true", headers=admin_headers).json
    assert active == []


def test_disable_project_keeps_prs(client, admin_headers, enabled_project, pr_trigger):
    pid = enabled_project.id
    enabled_project.locked = True
    db.session.commit()
    assert _patch(client, admin_headers, pid, enabled=False).status_code == 200
    assert client.get(pr_trigger, headers=admin_headers).status_code == 200


# ---------- link operations vs project lock / enabled ----------

def test_first_link_needs_no_lock_and_works_on_disabled_project(client, admin_headers, project, global_trigger_repo):
    assert project.enabled is False and project.locked is False
    r = client.put(f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}",
                   json={"watch_dir": "triggers"}, headers=admin_headers)
    assert r.status_code == 201


def test_link_put_patch_delete_gating_by_lock(client, admin_headers, project, linked_secret):
    url = f"/projects/{project.id}/secrets/test-creds"
    assert client.put(url, json={}, headers=admin_headers).status_code == 409
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 409
    assert client.delete(url, headers=admin_headers).status_code == 409

    r = _patch(client, admin_headers, project.id, locked=True)
    assert r.status_code == 200
    assert client.put(url, json={"enabled": False}, headers=admin_headers).status_code == 200
    assert client.patch(url, json={"enabled": True}, headers=admin_headers).status_code == 200
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).status_code == 404


def test_unlocking_restores_link_gating(client, admin_headers, lock_project, linked_secret):
    url = f"/projects/{lock_project.id}/secrets/test-creds"
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 200
    assert _patch(client, admin_headers, lock_project.id, locked=False).status_code == 200
    assert client.patch(url, json={"enabled": True}, headers=admin_headers).status_code == 409


def test_link_changes_allowed_on_locked_disabled_project(client, admin_headers, lock_project, linked_dataset, global_dataset):
    assert lock_project.enabled is False
    url = f"/projects/{lock_project.id}/datasets/{global_dataset.id}"
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).json["active"] is False
    assert client.delete(url, headers=admin_headers).status_code == 204


def test_link_changes_blocked_by_in_flight_task_even_when_locked(
    client, admin_headers, lock_project, linked_secret, make_task
):
    task = make_task()
    url = f"/projects/{lock_project.id}/secrets/test-creds"
    r = client.delete(url, headers=admin_headers)
    assert r.status_code == 409 and r.json["details"] == [task.id]
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 409


def test_revoke_is_not_gated_by_project_lock(client, admin_headers, project, linked_secret):
    url = f"/projects/{project.id}/secrets/test-creds"
    r = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert r.status_code == 200 and r.json["active"] is False


def test_link_operations_on_unknown_project_404(client, admin_headers, global_secret):
    assert client.put("/projects/9999/secrets/test-creds", json={}, headers=admin_headers).status_code == 404
    assert client.get("/projects/9999/secrets", headers=admin_headers).status_code == 404
    assert client.patch("/projects/9999/secrets/test-creds", json={"enabled": False}, headers=admin_headers).status_code == 404


# ---------- delete ----------

def test_delete_unknown_project_404(client, admin_headers):
    assert client.delete("/projects/9999", headers=admin_headers).status_code == 404


def test_delete_requires_lock(client, admin_headers, project):
    r = client.delete(f"/projects/{project.id}", headers=admin_headers)
    assert r.status_code == 409
    assert client.get(f"/projects/{project.id}", headers=admin_headers).status_code == 200


def test_delete_locked_empty_project(client, admin_headers, lock_project, other_project):
    r = client.delete(f"/projects/{lock_project.id}", headers=admin_headers)
    assert r.status_code == 204
    assert r.data == b""
    assert client.get(f"/projects/{lock_project.id}", headers=admin_headers).status_code == 404
    assert client.get(f"/projects/{other_project.id}", headers=admin_headers).status_code == 200
    assert client.get("/projects", headers=admin_headers).json["total"] == 1


def test_delete_twice_second_is_404(client, admin_headers, lock_project):
    assert client.delete(f"/projects/{lock_project.id}", headers=admin_headers).status_code == 204
    assert client.delete(f"/projects/{lock_project.id}", headers=admin_headers).status_code == 404


def test_delete_frees_the_name(client, admin_headers, lock_project):
    name = lock_project.name
    assert client.delete(f"/projects/{lock_project.id}", headers=admin_headers).status_code == 204
    assert _create(client, admin_headers, name=name).status_code == 201


def test_delete_blocked_by_task_in_flight(client, admin_headers, lock_project, make_task):
    task = make_task()
    r = client.delete(f"/projects/{lock_project.id}", headers=admin_headers)
    assert r.status_code == 409
    assert r.json["details"] == [task.id]
    assert client.get(f"/projects/{lock_project.id}", headers=admin_headers).status_code == 200


def test_delete_cascades_links_but_keeps_global_resources(
    client, admin_headers, lock_project, global_secret, global_dataset, global_trigger_repo, linked_secret,
    linked_dataset, linked_trigger_repo
):
    pid = lock_project.id
    r = client.delete(f"/projects/{pid}", headers=admin_headers)
    assert r.status_code == 204, r.json
    assert client.get(f"/projects/{pid}/secrets", headers=admin_headers).status_code == 404
    assert client.get(f"/global/secrets/{global_secret.label}", headers=admin_headers).status_code == 200
    assert client.get(f"/global/datasets/{global_dataset.id}", headers=admin_headers).status_code == 200
    assert client.get(f"/global/repositories/triggers/{global_trigger_repo.id}", headers=admin_headers).status_code == 200


def test_delete_project_with_prs_removes_project_triggers_keeps_global_prs(
    client, admin_headers, lock_project, pr_trigger, global_trigger_repo
):
    pid = lock_project.id
    r = client.delete(f"/projects/{pid}", headers=admin_headers)
    assert r.status_code == 204, r.json
    assert client.get(pr_trigger, headers=admin_headers).status_code == 404
    glob = client.get(f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests", headers=admin_headers)
    assert glob.status_code == 200 and glob.json["total"] == 1


def test_delete_project_with_finished_tasks(client, admin_headers, lock_project, make_task):
    task = make_task(status="FAILED")
    tid = task.id
    r = client.delete(f"/projects/{lock_project.id}", headers=admin_headers)
    assert r.status_code == 204, r.json
    assert client.get(f"/tasks/{tid}", headers=admin_headers).status_code == 404


def test_delete_project_with_yielded_task_and_pr(client, admin_headers, lock_project, pr_trigger, spec_raw):
    created = client.post(pr_trigger + "/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert created.status_code == 201, created.json
    tid = created.json["id"]
    client.patch(f"/tasks/{tid}", json={"status": "FAILED"}, headers=admin_headers)
    r = client.delete(f"/projects/{lock_project.id}", headers=admin_headers)
    assert r.status_code == 204, r.json
    assert client.get(f"/tasks/{tid}", headers=admin_headers).status_code == 404
    assert client.get(pr_trigger, headers=admin_headers).status_code == 404


def test_delete_project_with_results_repo_link_and_result(
    client, admin_headers, project, linked_results_repo, global_results_repo, make_task
):
    task = make_task(status="FAILED")
    posted = client.post("/projects/%d/results" % project.id,
                         json={"task_id": task.id, "results_repository_id": global_results_repo.id},
                         headers=admin_headers)
    assert posted.status_code == 201, posted.json
    client.patch(f"/projects/{project.id}/results/{posted.json['id']}",
                 json={"step": "OPENED", "state": "DELIVERED", "number": 1, "url": "https://x/pull/1"},
                 headers=admin_headers)
    project.locked = True
    db.session.commit()
    r = client.delete(f"/projects/{project.id}", headers=admin_headers)
    assert r.status_code in (204, 409), r.json  # never 500
    if r.status_code == 204:
        assert client.get(f"/global/repositories/results/{global_results_repo.id}", headers=admin_headers).status_code == 200


def test_delete_project_default_dataset_goes_with_it(client, admin_headers, project, linked_dataset, global_dataset):
    project_json = client.get(f"/projects/{project.id}", headers=admin_headers).json
    assert project_json["default_dataset_id"] == global_dataset.id
    project.locked = True
    db.session.commit()
    assert client.delete(f"/projects/{project.id}", headers=admin_headers).status_code == 204
    assert client.get(f"/global/datasets/{global_dataset.id}", headers=admin_headers).status_code == 200


def test_unlinking_default_dataset_clears_project_default(client, admin_headers, lock_project, linked_dataset, global_dataset):
    assert client.delete(f"/projects/{lock_project.id}/datasets/{global_dataset.id}", headers=admin_headers).status_code == 204
    assert client.get(f"/projects/{lock_project.id}", headers=admin_headers).json["default_dataset_id"] is None


def test_deleting_one_project_leaves_other_projects_links(
    client, admin_headers, project, other_project, global_secret
):
    for p in (project, other_project):
        assert client.put(f"/projects/{p.id}/secrets/test-creds", json={}, headers=admin_headers).status_code == 201
    project.locked = True
    db.session.commit()
    assert client.delete(f"/projects/{project.id}", headers=admin_headers).status_code == 204
    assert client.get(f"/projects/{other_project.id}/secrets/test-creds", headers=admin_headers).status_code == 200


def test_global_secret_deletable_after_linking_project_is_deleted(
    client, admin_headers, lock_project, linked_secret, k8s_client
):
    assert client.delete(f"/projects/{lock_project.id}", headers=admin_headers).status_code == 204
    assert client.delete("/global/secrets/test-creds", headers=admin_headers).status_code == 204
