"""
Dagster (role Dagster) writes only its pipeline state (SYSTEM_ONLY routes), which an admin cannot write. It
creates, changes and revokes no record: Cedar gives it no write (409). Users without a grant get the same 409.
"""
import pytest

from app.models.dataset import Dataset
from app.models.git_provider import GitProvider
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_secret import ProjectSecret
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.results_repository import ResultsRepository
from app.models.trigger_repository import TriggerRepository

from tests.test_global_resources import DS, PROV, RES, SEC, TRIG, ds_body, secret_body

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


@pytest.mark.usefixtures("global_dataset", "global_trigger_repo", "global_results_repo", "global_secret")
@pytest.mark.parametrize("method,url,body", SYSTEM_ROUTES, ids=[f"{m} {u}" for m, u, _ in SYSTEM_ROUTES])
def test_a_caller_who_is_neither_admin_nor_system_is_refused(client, post_json_user_header, method, url, body):
    """A User with no grant has no write on the record, or on Global for a create (409)."""
    assert getattr(client, method)(url, json=body, headers=post_json_user_header).status_code == 409


# (method, url, body) for the pull request, task and result writes Dagster makes, and the git token requests; the check runs
# before any lookup
STATE_ROUTES = [
    ("post", "/global/repositories/triggers/1/pull_requests", {"pull_requests": []}),
    ("patch", "/projects/1/repositories/triggers/1/pull_requests/1", {"state": "REJECTED", "state_cause": "x"}),
    ("post", "/projects/1/repositories/triggers/1/pull_requests/1/task", {"spec_raw": "{}"}),
    ("patch", "/projects/1/tasks/1", {"status": "RUNNING"}),
    ("post", "/projects/1/tasks/1/launch", None),
    ("post", "/projects/1/results", {"task_id": 1, "results_repository_id": 1}),
    ("patch", "/projects/1/results/1", {"step": "PUSHED"}),
    ("post", "/global/repositories/triggers/1/token", {}),
    ("post", "/global/repositories/results/1/token", {}),
]


@pytest.mark.parametrize("method,url,body", STATE_ROUTES, ids=[f"{m} {u}" for m, u, _ in STATE_ROUTES])
def test_an_admin_cannot_write_the_state_machines(client, admin_headers, method, url, body):
    assert getattr(client, method)(url, json=body, headers=admin_headers).status_code == 403


@pytest.mark.parametrize("url,body", [(DS, ds_body()), (PROV, PROVIDER), (SEC, secret_body())], ids=["dataset", "provider", "secret"])
def test_dagster_cannot_create_global_records(client, system_headers, global_secret, url, body):
    """Creating needs write on Global, which Cedar gives admins and the operator, not Dagster."""
    refused = client.post(url, json=body, headers=system_headers)
    assert refused.status_code == 409, refused.json()


@pytest.mark.parametrize("url_of,model,fixture", [
    (lambda r: f"{DS}/{r.id}", Dataset, "global_dataset"),
    (lambda r: f"{TRIG}/{r.id}", TriggerRepository, "global_trigger_repo"),
    (lambda r: f"{RES}/{r.id}", ResultsRepository, "global_results_repo"),
    (lambda r: f"{PROV}/{r.id}", GitProvider, "git_provider"),
    (lambda r: f"/projects/{r.id}", Project, "project"),
], ids=["dataset", "trigger repository", "results repository", "git provider", "project"])
def test_dagster_cannot_change_or_revoke_a_record(client, system_headers, request, url_of, model, fixture):
    resource = request.getfixturevalue(fixture)
    url = url_of(resource)
    refused = client.patch(url, json={"revoked": True}, headers=system_headers)
    assert refused.status_code == 409, refused.json()
    assert model.query.get(resource.id).revoked is False
    assert client.delete(url, headers=system_headers).status_code == 409


# Every route that accepts `revoked`: a write on the record (or its project), which the admin that owns them has.
# kind -> (fixtures it needs, url, model, the filter picking its row)
def _revoke_target(request, kind):
    get = request.getfixturevalue
    project = get("project")
    if kind == "dataset resource":
        get("assigned_dataset")
        ds = get("global_dataset")
        return f"/projects/{project.id}/datasets/{ds.id}", ProjectDataset, {"project_id": project.id}
    if kind == "secret resource":
        get("assigned_secret")
        return f"/projects/{project.id}/secrets/{get('global_secret').label}", ProjectSecret, {"project_id": project.id}
    if kind == "trigger resource":
        get("assigned_trigger_repo")
        return (f"/projects/{project.id}/repositories/triggers/{get('global_trigger_repo').id}",
                ProjectTriggerRepository, {"project_id": project.id})
    if kind == "results resource":
        get("assigned_results_repo")
        return (f"/projects/{project.id}/repositories/results/{get('global_results_repo').id}",
                ProjectResultsRepository, {"project_id": project.id})
    resource = get({"dataset": "global_dataset", "trigger repository": "global_trigger_repo",
                    "results repository": "global_results_repo", "git provider": "git_provider",
                    "project": "project"}[kind])
    url = {"dataset": DS, "trigger repository": TRIG, "results repository": RES, "git provider": PROV}.get(kind)
    model = {"dataset": Dataset, "trigger repository": TriggerRepository, "results repository": ResultsRepository,
             "git provider": GitProvider, "project": Project}[kind]
    return (f"{url}/{resource.id}" if url else f"/projects/{resource.id}"), model, {"id": resource.id}


REVOKE_KINDS = ["dataset", "trigger repository", "results repository", "git provider", "project",
                "dataset resource", "secret resource", "trigger resource", "results resource"]


def _revoked(model, where):
    return model.query.filter_by(**where).one().revoked


@pytest.mark.parametrize("kind", REVOKE_KINDS)
def test_only_a_writer_can_revoke(client, admin_headers, system_headers, post_json_user_header, request, kind):
    """Dagster and Users without a grant have no write (409)."""
    url, model, where = _revoke_target(request, kind)
    for headers, code in ((system_headers, 409), (post_json_user_header, 409)):
        assert client.patch(url, json={"revoked": True}, headers=headers).status_code == code
        assert _revoked(model, where) is False
    revoked = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert revoked.status_code == 200, revoked.json()
    assert _revoked(model, where) is True


@pytest.mark.parametrize("kind", REVOKE_KINDS)
def test_only_a_writer_can_unrevoke(client, admin_headers, system_headers, post_json_user_header, request, kind):
    url, model, where = _revoke_target(request, kind)
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    for headers, code in ((system_headers, 409), (post_json_user_header, 409)):
        assert client.patch(url, json={"revoked": False}, headers=headers).status_code == code
        assert _revoked(model, where) is True
    restored = client.patch(url, json={"revoked": False}, headers=admin_headers)
    assert restored.status_code == 200, restored.json()
    assert _revoked(model, where) is False
