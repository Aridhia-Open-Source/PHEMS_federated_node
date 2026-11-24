"""
The grants routes (ADR 0037): GET/POST/DELETE <record path>/grants and PUT <record path>/owner. Only a manage
holder (a user, or one of its groups) or SuperUser changes a record's grants; the owned_by user's manage grant
stays while they own it; only SuperUser claims or re-assigns.
"""
from datetime import datetime as dt

import pytest

from app.database.base_model import db
from app.models.grant import Grant
from app.models.project import Project
from tests.conftest import claims_for

# token -> the Keycloak user it verifies to, its node role and groups (None: the role's group only)
USERS = {
    "owner_token": ("id-owner", "owner", "Administrator", None),
    "other_token": ("id-other", "other", "Administrator", None),
    "member_token": ("id-member", "member", "Administrator", ["/roles/admins", "/studies/uc1"]),
    "super_token": ("id-super", "super", "SuperUser", None),
}


@pytest.fixture
def callers(token_claims):
    for token, (sub, username, role, groups) in USERS.items():
        token_claims[token] = claims_for(sub, username, role, groups)


def as_(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def project_path(client, callers) -> str:
    """A project created by owner_token, which so holds manage on it."""
    response = client.post("/projects", json={"name": "granted"}, headers=as_("owner_token"))
    assert response.status_code == 201, response.json()
    return f"/projects/{response.json()['id']}"


def grant(relation="read", subject_type="user", subject_id="id-other", **extra) -> dict:
    return {"relation": relation, "subject_type": subject_type, "subject_id": subject_id, **extra}


def add(client, path, token, body):
    return client.post(f"{path}/grants", json=body, headers=as_(token))


def listed(client, path) -> set[tuple]:
    response = client.get(f"{path}/grants", headers=as_("owner_token"))
    assert response.status_code == 200, response.json()
    return {(g["relation"], g["subject_type"], g["subject_id"]) for g in response.json()}


def grant_id(client, path, relation, subject_id, token="owner_token") -> int:
    response = client.get(f"{path}/grants", headers=as_(token))
    return next(g["id"] for g in response.json() if (g["relation"], g["subject_id"]) == (relation, subject_id))


# Listing and adding

def test_a_new_record_lists_its_creators_manage_grant(client, project_path):
    assert listed(client, project_path) == {("manage", "user", "id-owner")}


@pytest.mark.parametrize("relation", ["read", "assign", "execute", "operate", "write", "manage"])
def test_the_manage_holder_adds_any_relation(client, project_path, relation):
    response = add(client, project_path, "owner_token", grant(relation))

    assert response.status_code == 201, response.json()
    assert response.json()["created_by"] == "id-owner"
    assert (relation, "user", "id-other") in listed(client, project_path)


def test_an_unknown_relation_or_subject_type_is_a_400(client, project_path):
    assert add(client, project_path, "owner_token", grant("own")).status_code == 400
    assert add(client, project_path, "owner_token", grant(subject_type="role")).status_code == 400


def test_a_duplicate_grant_is_a_409(client, project_path):
    add(client, project_path, "owner_token", grant())

    response = add(client, project_path, "owner_token", grant())

    assert response.status_code == 409


def test_an_expiry_is_stored_as_naive_utc(client, project_path):
    response = add(client, project_path, "owner_token", grant(expires_at="2027-01-01T02:00:00+02:00"))

    assert response.status_code == 201, response.json()
    assert response.json()["expires_at"] == "2027-01-01 00:00:00"
    assert Grant.query.filter_by(subject_id="id-other").one().expires_at == dt(2027, 1, 1)


# Who may change grants

def test_a_caller_without_manage_cannot_add_and_is_told_the_owner(client, project_path):
    response = add(client, project_path, "other_token", grant(subject_id="id-member"))

    assert response.status_code == 409
    assert "owned by owner" in response.json()["error"]


def test_a_write_holder_cannot_grant(client, project_path):
    add(client, project_path, "owner_token", grant("write"))

    response = add(client, project_path, "other_token", grant(subject_id="id-member"))

    assert response.status_code == 409


def test_a_member_of_a_group_holding_manage_can_grant(client, project_path):
    add(client, project_path, "owner_token", grant("manage", "group", "/studies/uc1"))

    response = add(client, project_path, "member_token", grant())

    assert response.status_code == 201, response.json()


def test_an_expired_manage_grant_allows_nothing(client, project_path):
    add(client, project_path, "owner_token", grant("manage", expires_at="2020-01-01T00:00:00Z"))

    response = add(client, project_path, "other_token", grant(subject_id="id-member"))

    assert response.status_code == 409


def test_the_superuser_grants_without_a_grant(client, project_path):
    response = add(client, project_path, "super_token", grant())

    assert response.status_code == 201, response.json()


# Removing

def test_the_manage_holder_removes_a_grant(client, project_path):
    add(client, project_path, "owner_token", grant())

    response = client.delete(
        f"{project_path}/grants/{grant_id(client, project_path, 'read', 'id-other')}", headers=as_("owner_token")
    )

    assert response.status_code == 204
    assert listed(client, project_path) == {("manage", "user", "id-owner")}


def test_a_caller_without_manage_cannot_remove(client, project_path):
    add(client, project_path, "owner_token", grant())

    response = client.delete(
        f"{project_path}/grants/{grant_id(client, project_path, 'read', 'id-other')}", headers=as_("other_token")
    )

    assert response.status_code == 409


def test_the_owners_manage_grant_cannot_be_removed(client, project_path):
    response = client.delete(
        f"{project_path}/grants/{grant_id(client, project_path, 'manage', 'id-owner')}", headers=as_("super_token")
    )

    assert response.status_code == 409
    assert listed(client, project_path) == {("manage", "user", "id-owner")}


def test_a_grant_of_another_record_is_a_404(client, project_path):
    other = client.post("/projects", json={"name": "other"}, headers=as_("other_token")).json()["id"]
    foreign = grant_id(client, f"/projects/{other}", "manage", "id-other", token="other_token")

    response = client.delete(f"{project_path}/grants/{foreign}", headers=as_("owner_token"))

    assert response.status_code == 404


# Claiming and re-assigning

def test_only_the_superuser_claims(client, project_path):
    response = client.put(f"{project_path}/owner", headers=as_("other_token"))

    assert response.status_code == 409


def test_the_superuser_claims_a_record(client, project_path):
    response = client.put(f"{project_path}/owner", headers=as_("super_token"))

    assert response.status_code == 200, response.json()
    db.session.expire_all()
    assert Project.get_by_id(int(project_path.rsplit("/", 1)[1])).owned_by_id == "id-super"
    # The former owner keeps manage until a manage holder removes it
    assert listed(client, project_path) == {("manage", "user", "id-owner"), ("manage", "user", "id-super")}


def test_the_superuser_re_assigns_a_record_to_a_known_user(client, project_path):
    client.get("/projects", headers=as_("other_token"))  # other becomes a known user

    response = client.put(f"{project_path}/owner", json={"user_id": "id-other"}, headers=as_("super_token"))

    assert response.status_code == 200, response.json()
    db.session.expire_all()
    assert Project.get_by_id(int(project_path.rsplit("/", 1)[1])).owned_by_id == "id-other"
    assert ("manage", "user", "id-other") in listed(client, project_path)
    # The former owner's grant is no longer the owner's, so it can go
    response = client.delete(
        f"{project_path}/grants/{grant_id(client, project_path, 'manage', 'id-owner')}", headers=as_("super_token")
    )
    assert response.status_code == 204


def test_re_assigning_to_an_unknown_user_is_a_404(client, project_path):
    response = client.put(f"{project_path}/owner", json={"user_id": "id-nobody"}, headers=as_("super_token"))

    assert response.status_code == 404


# Every record path

def test_every_global_record_has_grant_routes(
    client, callers, global_secret, global_dataset, global_trigger_repo, global_results_repo,
):
    """Fixture records are owned by the admin (owned_by_admin), who manages them; SuperUser adds a grant too."""
    paths = [
        f"/global/secrets/{global_secret.label}", f"/global/datasets/{global_dataset.id}",
        f"/global/providers/{global_trigger_repo.provider_id}",
        f"/global/repositories/triggers/{global_trigger_repo.id}",
        f"/global/repositories/results/{global_results_repo.id}",
    ]
    for path in paths:
        assert add(client, path, "super_token", grant()).status_code == 201, path
        assert ("read", "user", "id-other") in listed(client, path), path


def test_a_missing_record_is_a_404(client, callers):
    assert client.get("/projects/999999/grants", headers=as_("owner_token")).status_code == 404
    assert client.get("/global/secrets/nope/grants", headers=as_("owner_token")).status_code == 404
