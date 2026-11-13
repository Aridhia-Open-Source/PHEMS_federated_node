"""
`revoked` is set by an admin-only PATCH, never on create: a POST that names it is a 400, whatever the value, and
creates nothing. One test per resource.
"""
import pytest

from app.models.dataset import Dataset
from app.models.git_provider import GitProvider
from app.models.project import Project
from app.models.results_repository import ResultsRepository
from app.models.trigger_repository import TriggerRepository

from tests.test_global_resources import DS, PROV, RES, TRIG, ds_body, repo_body

REVOKED = pytest.mark.parametrize("revoked", [True, False])


def refused(response):
    assert response.status_code == 400, response.json()
    assert "revoked" in response.json()["error"]


@REVOKED
def test_dataset_create_refuses_revoked(client, admin_headers, global_secret, revoked):
    refused(client.post(DS, json=ds_body(revoked=revoked), headers=admin_headers))
    assert Dataset.query.count() == 0


@REVOKED
def test_trigger_repository_create_refuses_revoked(client, admin_headers, global_secret, git_provider, revoked):
    refused(client.post(TRIG, json=repo_body(git_provider, revoked=revoked), headers=admin_headers))
    assert TriggerRepository.query.count() == 0


@REVOKED
def test_results_repository_create_refuses_revoked(client, admin_headers, global_secret, git_provider, revoked):
    refused(client.post(RES, json=repo_body(git_provider, revoked=revoked), headers=admin_headers))
    assert ResultsRepository.query.count() == 0


@REVOKED
def test_git_provider_create_refuses_revoked(client, admin_headers, revoked):
    body = {"name": "gt", "type": "gitea", "uri": "https://gitea.example.com", "api_uri": "https://gitea.example.com/api/v1",
            "revoked": revoked}
    refused(client.post(PROV, json=body, headers=admin_headers))
    assert GitProvider.query.count() == 0


@REVOKED
def test_project_create_refuses_revoked(client, admin_headers, revoked):
    refused(client.post("/projects", json={"name": "NewProject", "revoked": revoked}, headers=admin_headers))
    assert Project.query.count() == 0
