"""GET /tasks, the tasks of all projects."""
import pytest

from app.helpers.base_model import db
from app.models.project import Project


def ids(response):
    return [t["id"] for t in response.json["tasks"]]


def test_lists_the_tasks_of_every_project_with_their_project_id(client, admin_headers, make_task, project, other_project):
    first, second = make_task(), make_task(other_project)
    response = client.get("/tasks", headers=admin_headers)
    assert response.status_code == 200
    assert ids(response) == [first.id, second.id]
    assert [t["project_id"] for t in response.json["tasks"]] == [project.id, other_project.id]
    assert {"tasks", "total", "page", "per_page", "pages"} <= set(response.json)


def test_the_shape_is_the_project_lists(client, admin_headers, make_task, project):
    make_task()
    everywhere = client.get("/tasks", headers=admin_headers).json
    scoped = client.get(f"/projects/{project.id}/tasks", headers=admin_headers).json
    assert everywhere == scoped


def test_status_filter_single_and_list(client, admin_headers, make_task):
    pending, running, success = make_task(status="PENDING"), make_task(status="RUNNING"), make_task(status="SUCCESS")
    assert ids(client.get("/tasks?status=PENDING", headers=admin_headers)) == [pending.id]
    both = client.get("/tasks?status=PENDING,RUNNING", headers=admin_headers)
    assert ids(both) == [pending.id, running.id]
    assert success.id not in ids(both)


def test_an_invalid_status_is_a_400_listing_the_valid_ones(client, admin_headers):
    response = client.get("/tasks?status=PENDING,NOPE", headers=admin_headers)
    assert response.status_code == 400
    assert "NOPE" in response.json["error"] and "PENDING" in response.json["error"]


def test_project_enabled_keeps_enabled_projects_only(client, admin_headers, make_task, project, other_project):
    kept, dropped = make_task(), make_task(other_project)
    other_project.enabled = False
    db.session.commit()
    assert ids(client.get("/tasks?project_enabled=true", headers=admin_headers)) == [kept.id]
    assert ids(client.get("/tasks", headers=admin_headers)) == [kept.id, dropped.id]


def test_project_enabled_includes_a_revoked_project_like_the_projects_list(
    client, admin_headers, make_task, project, other_project
):
    revoked, plain = make_task(), make_task(other_project)
    project.revoked = True
    db.session.commit()
    listed = client.get("/projects?enabled=true", headers=admin_headers).json["items"]
    assert {p["id"] for p in listed} == {project.id, other_project.id}
    assert ids(client.get("/tasks?project_enabled=true", headers=admin_headers)) == [revoked.id, plain.id]


def test_project_enabled_must_be_a_boolean(client, admin_headers):
    assert client.get("/tasks?project_enabled=maybe", headers=admin_headers).status_code == 400


def test_pagination_and_clamping(client, admin_headers, make_task):
    created = [make_task() for _ in range(5)]
    page = client.get("/tasks?per_page=2&page=2", headers=admin_headers).json
    assert [t["id"] for t in page["tasks"]] == [created[2].id, created[3].id]
    assert (page["total"], page["pages"], page["page"], page["per_page"]) == (5, 3, 2, 2)
    clamped = client.get("/tasks?per_page=0&page=0", headers=admin_headers).json
    assert (clamped["page"], clamped["per_page"]) == (1, 1)


def test_a_soft_deleted_task_is_hidden(client, admin_headers, make_task):
    gone, kept = make_task(), make_task()
    gone.delete()
    assert ids(client.get("/tasks", headers=admin_headers)) == [kept.id]


def test_the_system_user_is_allowed(client, system_headers, make_task):
    task = make_task()
    response = client.get("/tasks?status=PENDING&project_enabled=true", headers=system_headers)
    assert response.status_code == 200
    assert ids(response) == [task.id]


def test_unauthenticated_is_refused(client):
    assert client.get("/tasks").status_code in (401, 403)
