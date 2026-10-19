"""
The Dagster System user (role System, not an admin) writes the global resources Dagster and fncli manage, and
can never revoke: `revoked` is admin only. Keycloak.is_token_valid skips the permission check for a System
token (tests/keycloak/test_tokens.py runs that for real), which the conftest mock mirrors, so no route needs to
opt in. A caller who is neither admin nor System is refused on all of them.
"""
import pytest

from app.models.dataset import Dataset
from app.models.git_provider import GitProvider
from app.models.project import Project
from app.models.results_repository import ResultsRepository
from app.models.trigger_repository import TriggerRepository

from tests.test_global_resources import DS, PROV, RES, SEC, TRIG, ds_body, repo_body, secret_body

REPO = {"provider_id": 1, "repo_path": "org/new", "secret_label": "test-creds"}
PROVIDER = {"name": "gt", "type": "gitea", "uri": "https://gitea.example.com", "api_uri": "https://gitea.example.com/api/v1"}
# (method, url, body) for the global write routes fncli and the Dagster client call; ids are 1, auth runs first
SYSTEM_ROUTES = [
    ("post", DS, ds_body()),
    ("delete", f"{DS}/1", None),
    ("post", TRIG, REPO),
    ("delete", f"{TRIG}/1", None),
    ("post", RES, REPO),
    ("delete", f"{RES}/1", None),
    ("post", PROV, PROVIDER),
    ("delete", f"{PROV}/1", None),
    ("post", SEC, secret_body()),
    ("patch", f"{SEC}/test-creds", {"values": {"TOKEN": "t2"}}),
]


@pytest.mark.parametrize("method,url,body", SYSTEM_ROUTES, ids=[f"{m} {u}" for m, u, _ in SYSTEM_ROUTES])
def test_a_caller_who_is_neither_admin_nor_system_is_refused(client, post_json_user_header, method, url, body):
    assert getattr(client, method)(url, json=body, headers=post_json_user_header).status_code == 403


def test_system_manages_datasets(client, system_headers, global_secret):
    created = client.post(DS, json=ds_body(), headers=system_headers)
    assert created.status_code == 201, created.json
    deleted = client.delete(f"{DS}/{created.json['id']}", query_string={"force": "true"}, headers=system_headers)
    assert deleted.status_code in (200, 204), deleted.json
    assert Dataset.query.count() == 0


def test_system_manages_trigger_repositories(client, system_headers, global_secret, git_provider):
    created = client.post(TRIG, json=repo_body(git_provider), headers=system_headers)
    assert created.status_code == 201, created.json
    deleted = client.delete(f"{TRIG}/{created.json['id']}", query_string={"force": "true"}, headers=system_headers)
    assert deleted.status_code in (200, 204), deleted.json
    assert TriggerRepository.query.count() == 0


def test_system_manages_results_repositories(client, system_headers, global_secret, git_provider):
    created = client.post(RES, json=repo_body(git_provider), headers=system_headers)
    assert created.status_code == 201, created.json
    deleted = client.delete(f"{RES}/{created.json['id']}", query_string={"force": "true"}, headers=system_headers)
    assert deleted.status_code in (200, 204), deleted.json
    assert ResultsRepository.query.count() == 0


def test_system_manages_git_providers(client, system_headers):
    created = client.post(PROV, json=PROVIDER, headers=system_headers)
    assert created.status_code == 201, created.json
    deleted = client.delete(f"{PROV}/{created.json['id']}", headers=system_headers)
    assert deleted.status_code in (200, 204), deleted.json
    assert GitProvider.query.count() == 0


def test_system_writes_secrets(client, system_headers, k8s_client):
    created = client.post(SEC, json=secret_body(), headers=system_headers)
    assert created.status_code == 201, created.json
    rotated = client.patch(f"{SEC}/new-creds", json={"values": {"TOKEN": "t2"}}, headers=system_headers)
    assert rotated.status_code == 200, rotated.json


@pytest.mark.parametrize("url_of,model,fixture", [
    (lambda r: f"{DS}/{r.id}", Dataset, "global_dataset"),
    (lambda r: f"{TRIG}/{r.id}", TriggerRepository, "global_trigger_repo"),
    (lambda r: f"{RES}/{r.id}", ResultsRepository, "global_results_repo"),
    (lambda r: f"{PROV}/{r.id}", GitProvider, "git_provider"),
    (lambda r: f"/projects/{r.id}", Project, "project"),
], ids=["dataset", "trigger repository", "results repository", "git provider", "project"])
def test_system_cannot_revoke(client, system_headers, request, url_of, model, fixture):
    resource = request.getfixturevalue(fixture)
    url = url_of(resource)
    refused = client.patch(url, json={"revoked": True}, headers=system_headers)
    assert refused.status_code == 403, refused.json
    assert model.query.get(resource.id).revoked is False
