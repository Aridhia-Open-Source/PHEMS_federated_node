"""
Lists show only what the caller may read (ADR 0037): a read grant to the user or one of its groups, unexpired; the
SuperUser, Dagster and, for global records, admins see everything. The filter runs before pagination, so totals and
pages count only the readable records.
"""
from datetime import datetime as dt, timedelta

import pytest

from app.database.base_model import db
from app.models.project import Project
from tests.conftest import SYSTEM_TOKEN, claims_for, owned_by_admin

# token -> a plain user in a study group, a second admin with no grants, and the SuperUser
OTHERS = {
    "reader_token": ("id-reader", "reader", "Users", ["/studies/uc1"]),
    "other_admin_token": ("id-other", "other", "Administrator", None),
    "super_token": ("id-super", "root", "SuperUser", None),
}


@pytest.fixture(autouse=True)
def others(token_claims):
    for token, (sub, username, role, groups) in OTHERS.items():
        token_claims[token] = claims_for(sub, username, role, groups)


def as_(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def grant(client, path: str, relation: str = "read", subject_id: str = "id-reader", subject_type: str = "user", **extra):
    """The admin, who owns the record, grants the relation on it."""
    body = {"relation": relation, "subject_type": subject_type, "subject_id": subject_id, **extra}
    response = client.post(f"{path}/grants", json=body, headers=as_("admin_token"))
    assert response.status_code == 201, response.json()


def names(client, path: str, token: str) -> list[str]:
    response = client.get(path, headers=as_(token))
    assert response.status_code == 200, response.json()
    body = response.json()
    return sorted(item["name"] for item in (body["items"] if isinstance(body, dict) else body))


def test_a_user_without_grants_lists_nothing(client, project, global_dataset, make_task):
    make_task()
    assert names(client, "/projects", "reader_token") == []
    assert names(client, "/global/datasets", "reader_token") == []
    assert client.get("/tasks", headers=as_("reader_token")).json()["total"] == 0


@pytest.mark.parametrize("subject_type,subject_id", [("user", "id-reader"), ("group", "/studies/uc1")])
def test_a_read_grant_to_the_user_or_its_group_lists_the_record(client, project, other_project, subject_type, subject_id):
    grant(client, f"/projects/{project.id}", subject_id=subject_id, subject_type=subject_type)
    assert names(client, "/projects", "reader_token") == [project.name]
    assert client.get(f"/projects/{project.id}", headers=as_("reader_token")).status_code == 200
    assert client.get(f"/projects/{other_project.id}", headers=as_("reader_token")).status_code == 409


def test_any_relation_lists_the_record(client, project):
    grant(client, f"/projects/{project.id}", "execute")
    assert names(client, "/projects", "reader_token") == [project.name]


def test_an_expired_grant_lists_nothing(client, project):
    grant(client, f"/projects/{project.id}", expires_at=(dt.utcnow() - timedelta(minutes=1)).isoformat())
    assert names(client, "/projects", "reader_token") == []


def test_a_global_record_grant_lists_it(client, global_dataset):
    grant(client, f"/global/datasets/{global_dataset.id}")
    assert names(client, "/global/datasets", "reader_token") == [global_dataset.name]


@pytest.mark.parametrize("token", ["super_token", SYSTEM_TOKEN])
def test_the_superuser_and_dagster_list_everything(client, project, other_project, global_dataset, token):
    assert names(client, "/projects", token) == sorted([project.name, other_project.name])
    assert names(client, "/global/datasets", token) == [global_dataset.name]


def test_an_admin_lists_every_global_record_but_only_its_projects(client, project, global_dataset):
    assert names(client, "/global/datasets", "other_admin_token") == [global_dataset.name]
    assert names(client, "/projects", "other_admin_token") == []


def test_totals_and_pages_count_only_readable_records(client):
    projects = [owned_by_admin(Project(name=f"p{i}", enabled=True)) for i in range(5)]
    for project in projects:
        project.add()
    for project in projects[:3]:
        grant(client, f"/projects/{project.id}")

    first = client.get("/projects?size=2", headers=as_("reader_token")).json()
    second = client.get("/projects?size=2&page=2", headers=as_("reader_token")).json()

    assert first["total"] == 3 and first["pages"] == 2
    assert sorted(p["name"] for p in first["items"] + second["items"]) == ["p0", "p1", "p2"]


def test_filters_and_the_grant_join_combine(client, project, other_project):
    other_project.enabled = False
    db.session.commit()
    grant(client, f"/projects/{project.id}")
    grant(client, f"/projects/{other_project.id}")
    assert names(client, "/projects?enabled=false", "reader_token") == [other_project.name]


def test_all_tasks_lists_only_the_readable_projects_tasks(client, project, other_project, make_task):
    mine = make_task()
    make_task(project=other_project)
    grant(client, f"/projects/{project.id}")

    body = client.get("/tasks", headers=as_("reader_token")).json()

    assert body["total"] == 1
    assert [task["id"] for task in body["items"]] == [mine.id]
