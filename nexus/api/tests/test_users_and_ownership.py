"""
The users table and the record creator (ADR 0035): each authenticated call upserts the caller's row, and the
creator of a record is its owner_id.
"""
from datetime import datetime as dt

import pytest

from app import create_app
from app.database.base_model import db
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.user import User
from tests.conftest import claims_for

PROV = "/global/providers"
# token -> the Keycloak user it verifies to, and its node role
USERS = {
    "admin_token": {"id": "id-admin", "username": "admin", "role": "Administrator"},
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


# Creator on create

def test_the_creator_of_a_record_is_its_owner(client, callers):
    by_person = create_provider(client, "person_token", "p1")
    by_service = create_provider(client, "service_token", "p2")

    assert by_person["owner"] == {"id": "id-person", "username": "person"}
    assert by_service["owner"] == {"id": "id-svc", "username": "svc"}


def test_a_project_and_its_assignment_are_owned_by_their_creator(client, callers, global_dataset):
    project_id = client.post("/projects", json={"name": "owned"}, headers=as_("service_token")).json()["id"]
    response = client.put(f"/projects/{project_id}/datasets/{global_dataset.id}", json={}, headers=as_("service_token"))

    assert response.status_code == 201
    assert response.json()["owner"]["id"] == "id-svc"
    assert Project.get_by_id(project_id).owner_id == "id-svc"
    assert ProjectDataset.query.filter_by(project_id=project_id).one().owner_id == "id-svc"


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


def test_every_write_route_is_classed_as_owned_or_not():
    """A new PUT, PATCH or DELETE route has to be added to one of the two lists, and tested if owned."""
    routes = {
        (method.upper(), path) for path, operations in create_app().openapi()["paths"].items()
        for method in operations if method in ("put", "patch", "delete")
    }
    assert routes == set(OWNED_WRITE_ROUTES) | UNOWNED_WRITE_ROUTES


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


@pytest.mark.skip(reason="owner groups removed; grants in T-057")
@pytest.mark.parametrize("method,path", list(OWNED_WRITE_ROUTES), ids=[f"{m} {p}" for m, p in OWNED_WRITE_ROUTES])
def test_a_write_to_a_record_locked_to_another_group_is_a_409(client, callers, every_owned_record, method, path):
    params = dict(every_owned_record)
    if path.startswith("/global/repositories/results/"):
        params["repo_id"] = params["results_repo_id"]
    body = OWNED_WRITE_ROUTES[(method, path)]

    response = client.request(method, path.format(**params), json=body, headers=as_("admin_token"))

    assert response.status_code == 409, response.json()
    assert "owned by" in response.json()["error"]
