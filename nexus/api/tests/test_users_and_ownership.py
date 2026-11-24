"""
The users table, the record creator and owner (ADR 0037): each authenticated call upserts the caller's row; the
creator of a record is its created_by, and of a project or global record also its owned_by, with a manage grant.
"""
from datetime import datetime as dt

import pytest

from app import create_app
from app.database.base_model import db
from app.models.grant import Grant
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.user import User
from tests.conftest import ADMIN_UUID, claims_for

PROV = "/global/providers"
# token -> the Keycloak user it verifies to, and its node role
USERS = {
    "admin_token": {"id": ADMIN_UUID, "username": "admin", "role": "Administrator"},
    "person_token": {"id": "id-person", "username": "person", "role": "Administrator"},
    "service_token": {"id": "id-svc", "username": "svc", "role": "Service"},
}


@pytest.fixture
def callers(token_claims):
    """Each token in USERS verifies to its own user."""
    for token, user in USERS.items():
        token_claims[token] = claims_for(user["id"], user["username"], user["role"])


def as_(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def provider_body(name="gt"):
    uri = f"https://{name}.example.com"
    return {"name": name, "type": "gitea", "uri": uri, "api_uri": f"{uri}/api/v1"}


def create_provider(client, token, name="gt") -> dict:
    response = client.post(PROV, json=provider_body(name), headers=as_(token))
    assert response.status_code == 201, response.json()
    return response.json()


# The caller and the users table

def test_a_call_creates_the_callers_row(client, callers):
    client.get(PROV, headers=as_("person_token"))
    client.get(PROV, headers=as_("service_token"))

    person, svc = db.session.get(User, "id-person"), db.session.get(User, "id-svc")
    assert (person.username, svc.username) == ("person", "svc")


def test_a_later_call_refreshes_the_row_instead_of_adding_one(client, callers, token_claims):
    client.get(PROV, headers=as_("person_token"))
    db.session.get(User, "id-person").last_seen_at = dt(2020, 1, 1)
    db.session.commit()
    token_claims["person_token"]["preferred_username"] = "renamed"

    client.get(PROV, headers=as_("person_token"))

    db.session.expire_all()
    assert User.query.filter_by(id="id-person").count() == 1
    user = db.session.get(User, "id-person")
    assert user.username == "renamed"
    assert user.last_seen_at > dt(2020, 1, 1)


def test_a_call_soon_after_the_last_leaves_the_row_alone_unless_the_username_changed(client, callers, token_claims):
    client.get(PROV, headers=as_("person_token"))
    seen = db.session.get(User, "id-person").last_seen_at

    client.get(PROV, headers=as_("person_token"))
    db.session.expire_all()
    assert db.session.get(User, "id-person").last_seen_at == seen

    token_claims["person_token"]["preferred_username"] = "renamed"
    client.get(PROV, headers=as_("person_token"))
    db.session.expire_all()
    assert db.session.get(User, "id-person").username == "renamed"


# Creator and owner on create

def grants_on(object_type: str, object_id: int) -> set[tuple]:
    db.session.expire_all()
    return {
        (g.relation, g.subject_type, g.subject_id)
        for g in Grant.query.filter_by(object_type=object_type, object_id=object_id)
    }


def test_the_creator_of_a_record_creates_and_owns_it_and_manages_it(client, callers):
    by_person = create_provider(client, "person_token", "p1")

    assert by_person["created_by"] == {"id": "id-person", "username": "person"}
    assert by_person["owned_by"] == {"id": "id-person", "username": "person"}
    assert grants_on("GitProvider", by_person["id"]) == {("manage", "user", "id-person")}


def test_an_operator_record_is_owned_by_its_account_and_managed_by_the_service_group(client, callers):
    by_service = create_provider(client, "service_token", "p2")

    assert by_service["owned_by"] == {"id": "id-svc", "username": "svc"}
    assert grants_on("GitProvider", by_service["id"]) == {("manage", "group", "/roles/service")}


def test_a_project_resource_has_a_creator_and_no_grants(client, callers, global_dataset):
    project_id = client.post("/projects", json={"name": "owned"}, headers=as_("service_token")).json()["id"]
    # The dataset is admin's: the operator needs assign on it
    client.post(
        f"/global/datasets/{global_dataset.id}/grants", headers=as_("admin_token"),
        json={"relation": "assign", "subject_type": "group", "subject_id": "/roles/service"},
    )
    response = client.put(f"/projects/{project_id}/datasets/{global_dataset.id}", json={}, headers=as_("service_token"))

    assert response.status_code == 201
    assert response.json()["created_by"]["id"] == "id-svc"
    assert "owned_by" not in response.json()
    project = Project.get_by_id(project_id)
    assert (project.created_by_id, project.owned_by_id) == ("id-svc", "id-svc")
    assert ProjectDataset.query.filter_by(project_id=project_id).one().created_by_id == "id-svc"
    # Grants on the project and the global records, none on the assignment
    assert "ProjectDataset" not in {g.object_type for g in Grant.query}
    assert Grant.query.filter_by(object_type="Project", object_id=project_id).count() == 1


def test_deleting_a_record_deletes_its_grants(client, callers):
    provider = create_provider(client, "person_token", "p1")

    response = client.delete(f"{PROV}/{provider['id']}", headers=as_("person_token"))

    assert response.status_code == 204
    assert grants_on("GitProvider", provider["id"]) == set()


# Every write route on a record, walked from the OpenAPI document

OWNED_WRITE_ROUTES = {
    ("PATCH", "/global/providers/{provider_id}"): {"name": "renamed"},
    ("DELETE", "/global/providers/{provider_id}"): None,
    ("PATCH", "/global/secrets/{label}"): {"enabled": False},
    ("DELETE", "/global/secrets/{label}"): None,
    ("PATCH", "/global/repositories/triggers/{repo_id}"): {"enabled": False},
    ("DELETE", "/global/repositories/triggers/{repo_id}"): None,
    ("PATCH", "/global/repositories/results/{repo_id}"): {"enabled": False},
    ("DELETE", "/global/repositories/results/{repo_id}"): None,
    ("PATCH", "/global/datasets/{dataset_id}"): {"enabled": False},
    ("DELETE", "/global/datasets/{dataset_id}"): None,
    ("PATCH", "/projects/{project_id}"): {"enabled": False},
    ("DELETE", "/projects/{project_id}"): None,
    ("PUT", "/projects/{project_id}/datasets/{dataset_id}"): {},
    ("PATCH", "/projects/{project_id}/datasets/{dataset_id}"): {"enabled": False},
    ("DELETE", "/projects/{project_id}/datasets/{dataset_id}"): None,
    ("PUT", "/projects/{project_id}/secrets/{label}"): {},
    ("PATCH", "/projects/{project_id}/secrets/{label}"): {"enabled": False},
    ("DELETE", "/projects/{project_id}/secrets/{label}"): None,
    ("PUT", "/projects/{project_id}/repositories/triggers/{repo_id}"): {"watch_dir": "t", "base_branch": "main"},
    ("PATCH", "/projects/{project_id}/repositories/triggers/{repo_id}"): {"enabled": False},
    ("DELETE", "/projects/{project_id}/repositories/triggers/{repo_id}"): None,
    ("PUT", "/projects/{project_id}/repositories/results/{repository_id}"): {"target_dir": "r", "base_branch": "main"},
    ("PATCH", "/projects/{project_id}/repositories/results/{repository_id}"): {"enabled": False},
    ("DELETE", "/projects/{project_id}/repositories/results/{repository_id}"): None,
}
# Write routes on records that have no owner
UNOWNED_WRITE_ROUTES = {
    ("PATCH", "/dagster/sensors"),
    ("PATCH", "/dagster/sensors/{name}"),
    ("PATCH", "/projects/{project_id}/repositories/triggers/{repo_id}/pull_requests/{number}"),
    ("PATCH", "/projects/{project_id}/results/{result_id}"),
    ("PATCH", "/projects/{project_id}/tasks/{task_id}"),
    ("PUT", "/global/users/reset-password"),
}
# The grants routes (grants_api), checked there: a manage holder or SuperUser
GRANT_ROUTES = {
    (method, f"{record}{route}")
    for record in (
        "/projects/{project_id}", "/global/datasets/{dataset_id}", "/global/providers/{provider_id}",
        "/global/secrets/{label}", "/global/repositories/triggers/{repo_id}", "/global/repositories/results/{repo_id}",
    )
    for method, route in (("DELETE", "/grants/{grant_id}"), ("PUT", "/owner"))
}


def test_every_write_route_is_classed_as_owned_or_not():
    """A new PUT, PATCH or DELETE route has to be added to one of the lists, and tested if owned."""
    routes = {
        (method.upper(), path) for path, operations in create_app().openapi()["paths"].items()
        for method in operations if method in ("put", "patch", "delete")
    }
    assert routes == set(OWNED_WRITE_ROUTES) | UNOWNED_WRITE_ROUTES | GRANT_ROUTES


@pytest.fixture
def every_owned_record(
    client, project, global_secret, global_dataset, global_trigger_repo, global_results_repo,
    assigned_dataset, assigned_secret, assigned_trigger_repo, assigned_results_repo,
) -> dict:
    """One of each owned record; the path parameters that address them."""
    return {
        "provider_id": global_trigger_repo.provider_id, "label": global_secret.label,
        "dataset_id": global_dataset.id, "project_id": project.id,
        "repo_id": global_trigger_repo.id, "repository_id": global_results_repo.id,
        "results_repo_id": global_results_repo.id,
    }


@pytest.mark.parametrize("method,path", list(OWNED_WRITE_ROUTES), ids=[f"{m} {p}" for m, p in OWNED_WRITE_ROUTES])
def test_a_write_without_a_grant_is_a_409_and_changes_nothing(client, callers, every_owned_record, method, path):
    """The records are admin's; person is an admin too, with no grant on any of them."""
    params = dict(every_owned_record)
    if path.startswith("/global/repositories/results/"):
        params["repo_id"] = params["results_repo_id"]
    url = path.format(**params)
    before = client.get(url, headers=as_("admin_token")).json()

    response = client.request(method, url, json=OWNED_WRITE_ROUTES[(method, path)], headers=as_("person_token"))

    assert response.status_code == 409, response.json()
    assert "owned by admin" in response.json()["error"]
    db.session.expire_all()
    assert client.get(url, headers=as_("admin_token")).json() == before


# Every read route on a record, walked from the OpenAPI document

# Reads of one record, or of something under a project or a record: read on that record or project
RECORD_READ_ROUTES = {
    "/global/datasets/{dataset_id}", "/global/datasets/{dataset_id}/grants",
    "/global/datasets/{dataset_id}/healthcheck",
    "/global/providers/{provider_id}", "/global/providers/{provider_id}/grants",
    "/global/providers/{provider_id}/healthcheck",
    "/global/repositories/results/{repo_id}", "/global/repositories/results/{repo_id}/grants",
    "/global/repositories/results/{repository_id}/healthcheck",
    "/global/repositories/triggers/{repo_id}", "/global/repositories/triggers/{repo_id}/grants",
    "/global/repositories/triggers/{repo_id}/pull_requests",
    "/global/repositories/triggers/{repository_id}/healthcheck",
    "/global/secrets/{label}", "/global/secrets/{label}/grants", "/global/secrets/{label}/healthcheck",
    "/projects/{project_id}", "/projects/{project_id}/grants", "/projects/{project_id}/healthcheck",
    "/projects/{project_id}/datasets", "/projects/{project_id}/datasets/{dataset_id}",
    "/projects/{project_id}/datasets/{dataset_id}/healthcheck",
    "/projects/{project_id}/secrets", "/projects/{project_id}/secrets/{label}",
    "/projects/{project_id}/secrets/{label}/healthcheck",
    "/projects/{project_id}/repositories/results", "/projects/{project_id}/repositories/results/{repository_id}",
    "/projects/{project_id}/repositories/results/{repository_id}/healthcheck",
    "/projects/{project_id}/repositories/triggers", "/projects/{project_id}/repositories/triggers/{repo_id}",
    "/projects/{project_id}/repositories/triggers/{repo_id}/pull_requests",
    "/projects/{project_id}/repositories/triggers/{repo_id}/pull_requests/{number}",
    "/projects/{project_id}/repositories/triggers/{repository_id}/healthcheck",
    "/projects/{project_id}/results", "/projects/{project_id}/results/{result_id}",
    "/projects/{project_id}/tasks", "/projects/{project_id}/tasks/{task_id}",
    "/projects/{project_id}/tasks/{task_id}/config", "/projects/{project_id}/tasks/{task_id}/logs",
    "/projects/{project_id}/tasks/{task_id}/results", "/projects/{project_id}/tasks/{task_id}/trigger",
}
# Lists, narrowed to what the caller may read (tests/test_list_filtering.py)
LIST_ROUTES = {
    "/global/datasets", "/global/providers", "/global/repositories/results", "/global/repositories/triggers",
    "/global/secrets", "/projects", "/tasks",
}
# No record: probes, and the admin-only routes (tests/test_unchecked_routes.py)
UNCHECKED_READ_ROUTES = {
    "/ready_check", "/health_check", "/global/users", "/global/healthcheck", "/dagster/sensors",
    "/dagster/sensors/{name}",
}


def test_every_read_route_is_classed():
    """A new GET route has to be added to one of the lists, and tested."""
    routes = {path for path, operations in create_app().openapi()["paths"].items() if "get" in operations}
    assert routes == RECORD_READ_ROUTES | LIST_ROUTES | UNCHECKED_READ_ROUTES


@pytest.mark.parametrize("path", sorted(RECORD_READ_ROUTES))
def test_a_read_without_a_grant_is_a_409(client, token_claims, every_owned_record, path):
    """The records are admin's; reader is a plain user with no grant on any of them."""
    token_claims["reader_token"] = claims_for("id-reader", "reader", "Users")
    params = {**every_owned_record, "task_id": 1, "result_id": 1, "number": 1}
    if path.startswith("/global/repositories/results/"):
        params["repo_id"] = params["repository_id"] = params["results_repo_id"]
    elif path.startswith("/global/repositories/triggers/"):
        params["repository_id"] = params["repo_id"]

    response = client.get(path.format(**params), headers=as_("reader_token"))

    assert response.status_code == 409, response.json()
    assert "You cannot read" in response.json()["error"]
