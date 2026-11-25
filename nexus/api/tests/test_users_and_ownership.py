"""
The users table and record ownership (ADR 0036): each authenticated call upserts the caller's row; the creator
owns a record; a record created by a member of an owner group (OWNER_GROUPS, by default service-account) is
locked to that group, and every write route loads its record through get_for_write, which refuses anyone else
with a 409.
"""
from datetime import datetime as dt
from types import SimpleNamespace

import pytest

from app import create_app
from app.database.base_model import db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.rules.ownership import get_for_write
from app.helpers.wrappers import token_groups
from app.models.git_provider import GitProvider
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.user import OwnedMixin, User

PROV = "/global/providers"
GROUP = "service-account"
# token -> the Keycloak user it decodes to, and its realm roles
USERS = {
    "admin_token": {"id": "id-admin", "username": "admin", "roles": ["Administrator"]},
    "person_token": {"id": "id-person", "username": "person", "roles": ["Administrator"]},
    "service_token": {"id": "id-svc", "username": "svc", "roles": [GROUP]},
    "other_service_token": {"id": "id-svc2", "username": "svc2", "roles": [GROUP]},
}


@pytest.fixture
def callers(mock_kc_client):
    """Each token in USERS decodes to its own user, and holds every scope."""
    kc = mock_kc_client["wrappers_kc"].return_value
    kc.decode_token.side_effect = lambda token: {
        "username": USERS[token]["username"], "realm_access": {"roles": USERS[token]["roles"]}
    }
    kc.get_user_by_username.side_effect = lambda username: next(
        u for u in USERS.values() if u["username"] == username
    )
    kc.is_token_valid.side_effect = lambda token, *args, **kwargs: token in USERS


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

def test_the_callers_groups_are_its_realm_roles_and_keycloak_groups():
    token_info = {"realm_access": {"roles": ["Users", GROUP]}, "groups": ["/ops"]}
    assert token_groups(token_info) == {"Users", GROUP, "ops"}
    assert token_groups({}) == frozenset()


def test_a_call_creates_the_callers_row(client, callers):
    client.get(PROV, headers=as_("person_token"))
    client.get(PROV, headers=as_("service_token"))

    person, svc = db.session.get(User, "id-person"), db.session.get(User, "id-svc")
    assert (person.username, svc.username) == ("person", "svc")


def test_a_later_call_refreshes_the_row_instead_of_adding_one(client, callers, monkeypatch):
    client.get(PROV, headers=as_("person_token"))
    db.session.get(User, "id-person").last_seen_at = dt(2020, 1, 1)
    db.session.commit()
    monkeypatch.setitem(USERS["person_token"], "username", "renamed")

    client.get(PROV, headers=as_("person_token"))

    db.session.expire_all()
    assert User.query.filter_by(id="id-person").count() == 1
    user = db.session.get(User, "id-person")
    assert user.username == "renamed"
    assert user.last_seen_at > dt(2020, 1, 1)


def test_a_call_soon_after_the_last_leaves_the_row_alone_unless_the_username_changed(client, callers, monkeypatch):
    client.get(PROV, headers=as_("person_token"))
    seen = db.session.get(User, "id-person").last_seen_at

    client.get(PROV, headers=as_("person_token"))
    db.session.expire_all()
    assert db.session.get(User, "id-person").last_seen_at == seen

    monkeypatch.setitem(USERS["person_token"], "username", "renamed")
    client.get(PROV, headers=as_("person_token"))
    db.session.expire_all()
    assert db.session.get(User, "id-person").username == "renamed"


def test_the_owner_groups_are_a_setting(client, callers, monkeypatch):
    monkeypatch.setattr("app.helpers.wrappers.OWNER_GROUPS", ["Administrator"])

    provider = create_provider(client, "person_token")

    assert provider["owner_group"] == "Administrator"


# Owner on create

def test_the_creator_owns_the_record_and_a_service_locks_it_to_its_group(client, callers):
    by_person = create_provider(client, "person_token", "p1")
    by_service = create_provider(client, "service_token", "p2")

    assert (by_person["owner"], by_person["owner_group"]) == ({"id": "id-person", "username": "person"}, None)
    assert (by_service["owner"], by_service["owner_group"]) == ({"id": "id-svc", "username": "svc"}, GROUP)


def test_a_project_and_its_assignment_are_owned_by_their_creator(client, callers, global_dataset):
    project_id = client.post("/projects", json={"name": "owned"}, headers=as_("service_token")).json()["id"]
    response = client.put(f"/projects/{project_id}/datasets/{global_dataset.id}", json={}, headers=as_("service_token"))

    assert response.status_code == 201
    assert (response.json()["owner"]["id"], response.json()["owner_group"]) == ("id-svc", GROUP)
    assert Project.get_by_id(project_id).owner_group == GROUP
    assert ProjectDataset.query.filter_by(project_id=project_id).one().owner_id == "id-svc"


# Changes

def test_anyone_may_change_an_open_record(client, callers):
    provider = create_provider(client, "person_token")

    response = client.patch(f"{PROV}/{provider['id']}", json={"name": "renamed"}, headers=as_("admin_token"))

    assert response.status_code == 200
    assert (response.json()["owner"]["id"], response.json()["owner_group"]) == ("id-person", None)


def test_a_service_that_writes_an_open_record_takes_it_over(client, callers):
    provider = create_provider(client, "person_token")

    response = client.patch(f"{PROV}/{provider['id']}", json={"name": "renamed"}, headers=as_("service_token"))

    assert response.status_code == 200
    assert (response.json()["owner"]["id"], response.json()["owner_group"]) == ("id-svc", GROUP)


def test_a_member_of_the_owner_group_may_change_the_record_and_takes_it_over(client, callers):
    provider = create_provider(client, "service_token")

    response = client.patch(f"{PROV}/{provider['id']}", json={"name": "renamed"}, headers=as_("other_service_token"))

    assert response.status_code == 200
    assert (response.json()["name"], response.json()["owner"]["id"]) == ("renamed", "id-svc2")


def test_a_change_by_someone_outside_the_owner_group_is_a_409(client, callers):
    provider = create_provider(client, "service_token")

    patched = client.patch(f"{PROV}/{provider['id']}", json={"name": "renamed"}, headers=as_("admin_token"))
    deleted = client.delete(f"{PROV}/{provider['id']}", headers=as_("admin_token"))

    assert patched.status_code == 409
    assert f"owned by {GROUP}" in patched.json()["error"]
    assert deleted.status_code == 409
    db.session.expire_all()
    provider = GitProvider.get_by_id(provider["id"])
    assert (provider.name, provider.deleted_at, provider.owner_id) == ("gt", None, "id-svc")


def test_an_administrator_has_no_override_on_a_locked_record(client, callers, mock_kc_client):
    """No admin bypass: even an admin-only change (revoking) by an Administrator outside the group is a 409."""
    provider = create_provider(client, "service_token")
    assert mock_kc_client["wrappers_kc"].return_value.is_user_admin("admin_token")

    response = client.patch(f"{PROV}/{provider['id']}", json={"revoked": True}, headers=as_("admin_token"))

    assert response.status_code == 409
    assert f"owned by {GROUP}" in response.json()["error"]
    db.session.expire_all()
    assert GitProvider.get_by_id(provider["id"]).revoked is False


# get_for_write

def _caller(groups=()):
    groups = frozenset(groups)
    return SimpleNamespace(user=SimpleNamespace(id="id-person"), groups=groups, owner_group=None)


def test_get_for_write_on_a_missing_record_is_a_404_or_none_when_optional(client):
    with pytest.raises(DBRecordNotFoundError) as error:
        get_for_write(db.session, GitProvider, 999, _caller(), missing="no such provider")
    assert (error.value.code, error.value.description) == (404, "no such provider")
    assert get_for_write(db.session, GitProvider, {"name": "none"}, _caller(), optional=True) is None


def test_the_lock_can_be_narrowed_to_some_fields(client, git_provider, monkeypatch):
    git_provider.owner_group = GROUP
    monkeypatch.setattr(GitProvider, "owner_locked_fields", frozenset({"uri"}))

    assert get_for_write(db.session, GitProvider, git_provider.id, _caller(), fields={"enabled"}) is git_provider
    with pytest.raises(InvalidRequest) as error:
        get_for_write(db.session, GitProvider, git_provider.id, _caller(), fields={"enabled", "uri"})
    assert error.value.code == 409
    with pytest.raises(InvalidRequest):
        get_for_write(db.session, GitProvider, git_provider.id, _caller())


# Every write route on an owned record goes through get_for_write

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
    """One of each owned record, all locked to GROUP; the path parameters that address them."""
    for model in OwnedMixin.__subclasses__():
        db.session.query(model).update({"owner_group": GROUP})
    db.session.commit()
    return {
        "provider_id": global_trigger_repo.provider_id, "label": global_secret.label,
        "dataset_id": global_dataset.id, "project_id": project.id,
        "repo_id": global_trigger_repo.id, "repository_id": global_results_repo.id,
        "results_repo_id": global_results_repo.id,
    }


@pytest.mark.parametrize("method,path", list(OWNED_WRITE_ROUTES), ids=[f"{m} {p}" for m, p in OWNED_WRITE_ROUTES])
def test_a_write_to_a_record_locked_to_another_group_is_a_409(client, callers, every_owned_record, method, path):
    params = dict(every_owned_record)
    if path.startswith("/global/repositories/results/"):
        params["repo_id"] = params["results_repo_id"]
    body = OWNED_WRITE_ROUTES[(method, path)]

    response = client.request(method, path.format(**params), json=body, headers=as_("admin_token"))

    assert response.status_code == 409, response.json()
    assert f"owned by {GROUP}" in response.json()["error"]
