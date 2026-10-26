"""Healthcheck routes. A failed check is reported in the body with a 200, never a 500."""
from functools import partial
from unittest.mock import MagicMock

import pytest
import requests
from kubernetes.client.exceptions import ApiException

from app.helpers.base_model import db
from app.models.dataset import Dataset
from app.models.git_provider import ConnectionCheck, ConnectionStatus
from app.models.git_repository import GitRepositoryMixin

_REAL_DATASET_PREPARE = Dataset.prepare_connection_check
_REAL_REPO_PREPARE = GitRepositoryMixin.prepare_connection_check

HEALTH_CHECK_KEYS = {"message", "status_code", "latency_ms"}
OK = lambda: ConnectionCheck(ConnectionStatus.OK, "OK")  # noqa: E731


def bad(status, message="boom", code=None):
    return lambda: ConnectionCheck(status, message, code)


def get(client, admin_headers, url):
    return client.get(url, headers=admin_headers, json={})


def set_secret_data(k8s_client, data):
    k8s_client["read_namespaced_secret_mock"].return_value.data = data


def real_repo_check(mock_connection_checks):
    """Run the real GitRepositoryMixin._request_check (requests.get is patched by the caller)."""
    mock_connection_checks["repository"].return_value = partial(
        GitRepositoryMixin._request_check, "https://api.example/repos/x", "tok"
    )


def fake_response(status_code, body=None, reason="Reason"):
    response = MagicMock(status_code=status_code, ok=status_code < 400, reason=reason)
    response.json.return_value = body
    return response


# ---------- global aggregate ----------

def test_global_healthcheck_empty_is_ok(client, admin_headers, k8s_client, mock_connection_checks):
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.status_code == 200 and r.json["status"] == "ok"
    assert [r.json[k] for k in ("datasets", "secrets", "trigger_repositories", "results_repositories")] == [[]] * 4


def test_global_healthcheck_shapes_and_per_resource_ok(
    client, admin_headers, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo, global_results_repo
):
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.json["status"] == "ok"
    assert set(r.json) == {"status", "datasets", "secrets", "trigger_repositories", "results_repositories"}
    assert set(r.json["datasets"][0]) >= {"id", "name", "host", "port", "type", "enabled", "status", "health_check"}
    assert set(r.json["secrets"][0]) >= {"label", "provider", "enabled", "status", "health_check", "keys", "missing_keys"}
    for kind in ("trigger_repositories", "results_repositories"):
        assert set(r.json[kind][0]) >= {"id", "uri", "provider", "enabled", "status", "health_check"}
    for kind in ("datasets", "secrets", "trigger_repositories", "results_repositories"):
        assert r.json[kind][0]["status"] == "ok"
        assert set(r.json[kind][0]["health_check"]) == HEALTH_CHECK_KEYS

    for url in (f"/global/datasets/{global_dataset.id}/healthcheck", "/global/secrets/test-creds/healthcheck",
                f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck",
                f"/global/repositories/results/{global_results_repo.id}/healthcheck"):
        single = get(client, admin_headers, url)
        assert single.status_code == 200 and single.json["status"] == "ok", url


def test_global_aggregate_error_when_any_resource_fails(
    client, admin_headers, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo,
    make_trigger_repo, global_results_repo
):
    mock_connection_checks["dataset"].return_value = bad(ConnectionStatus.UNREACHABLE, "refused")
    second = make_trigger_repo(uri="github.com/org/second")
    # repositories are prepared in order: first trigger, second trigger, results
    mock_connection_checks["repository"].side_effect = [OK, bad(ConnectionStatus.NOT_FOUND, "Not Found", 404), OK]
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.status_code == 200 and r.json["status"] == "error"
    assert r.json["datasets"][0]["status"] == "unreachable"
    assert r.json["datasets"][0]["health_check"]["message"] == "refused"
    triggers = r.json["trigger_repositories"]
    assert [(t["id"], t["status"]) for t in triggers] == [(global_trigger_repo.id, "ok"), (second.id, "not_found")]
    assert triggers[1]["health_check"]["status_code"] == 404
    assert r.json["results_repositories"][0]["status"] == "ok"


def test_every_failure_status_is_reported_verbatim(
    client, admin_headers, k8s_client, mock_connection_checks, global_trigger_repo
):
    for status in ("unauthorized", "not_found", "unreachable", "secret_missing", "error"):
        mock_connection_checks["repository"].return_value = bad(ConnectionStatus(status), "msg", 418)
        r = get(client, admin_headers, f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck")
        assert r.status_code == 200 and r.json["status"] == status
        assert r.json["health_check"] == {"message": "msg", "status_code": 418, "latency_ms": None}


def test_disabled_resource_is_still_checked_and_flagged(
    client, admin_headers, k8s_client, mock_connection_checks, global_dataset
):
    global_dataset.enabled = False
    db.session.commit()
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.json["status"] == "ok"
    assert r.json["datasets"][0]["enabled"] is False and r.json["datasets"][0]["status"] == "ok"


# ---------- secrets ----------

@pytest.mark.parametrize("fixture, data, missing", [
    ("global_secret", {"SOMETHING": "YQ=="}, []),  # a secret nobody uses needs no particular key
    ("global_trigger_repo", {"USERNAME": "YQ==", "PASSWORD": "Yg=="}, ["TOKEN"]),  # repositories need TOKEN
    ("global_dataset", {"TOKEN": "YQ=="}, ["PASSWORD", "USERNAME"]),  # datasets need USERNAME and PASSWORD
])
def test_secret_missing_keys_depend_on_its_users(
    client, admin_headers, k8s_client, mock_connection_checks, request, fixture, data, missing
):
    request.getfixturevalue(fixture)
    set_secret_data(k8s_client, data)
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.status_code == 200
    assert r.json["missing_keys"] == missing
    assert r.json["status"] == ("secret_missing" if missing else "ok")
    assert r.json["keys"] == sorted(data)
    if missing:
        assert missing[0] in r.json["health_check"]["message"]


def test_secret_absent_from_store_and_values_never_exposed(
    client, admin_headers, k8s_client, mock_connection_checks, global_trigger_repo
):
    set_secret_data(k8s_client, {"TOKEN": "c3VwZXJzZWNyZXQ="})
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert "c3VwZXJzZWNyZXQ=" not in r.get_data(as_text=True) and "supersecret" not in r.get_data(as_text=True)

    k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=404)
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.status_code == 200 and r.json["status"] == "secret_missing" and r.json["keys"] == []
    assert "not in its store" in r.json["health_check"]["message"]
    assert get(client, admin_headers, "/global/healthcheck").json["status"] == "error"


def test_repository_and_dataset_check_report_secret_missing(
    client, admin_headers, k8s_client, mock_connection_checks, mocker, global_trigger_repo, global_dataset
):
    mocker.patch.object(GitRepositoryMixin, "prepare_connection_check", _REAL_REPO_PREPARE)
    mocker.patch.object(Dataset, "prepare_connection_check", _REAL_DATASET_PREPARE)
    repo_url = f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck"
    dataset_url = f"/global/datasets/{global_dataset.id}/healthcheck"

    for data in ({"USERNAME": "YQ==", "PASSWORD": "Yg=="}, None):  # no TOKEN / no data at all
        set_secret_data(k8s_client, data)
        r = get(client, admin_headers, repo_url)
        assert r.status_code == 200 and r.json["status"] == "secret_missing"
    set_secret_data(k8s_client, {"TOKEN": "YQ=="})
    r = get(client, admin_headers, dataset_url)
    assert r.json["status"] == "secret_missing" and "USERNAME" in r.json["health_check"]["message"]

    k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=404)
    r = get(client, admin_headers, repo_url)
    assert r.json["status"] == "secret_missing" and r.json["health_check"]["status_code"] is None


# ---------- connection exceptions and HTTP mapping ----------

def test_repository_http_status_and_exceptions_map_to_status(
    client, admin_headers, k8s_client, mock_connection_checks, mocker, global_trigger_repo
):
    url = f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck"
    real_repo_check(mock_connection_checks)
    for code, expected in [(200, "ok"), (401, "unauthorized"), (403, "unauthorized"), (404, "not_found"), (500, "error")]:
        mocker.patch("app.models.git_provider.requests.get", return_value=fake_response(code, {"message": "Bad credentials"}))
        r = get(client, admin_headers, url)
        assert r.status_code == 200 and r.json["status"] == expected, code
        assert r.json["health_check"]["status_code"] == code and r.json["health_check"]["message"] == "Bad credentials"

    response = fake_response(502, reason="Bad Gateway")  # an error body that is not JSON falls back to the reason
    response.json.side_effect = ValueError("no json")
    mocker.patch("app.models.git_provider.requests.get", return_value=response)
    assert get(client, admin_headers, url).json["health_check"]["message"] == "Bad Gateway"

    for exc in (requests.Timeout("slow"), requests.ConnectionError("down")):
        mocker.patch("app.models.git_provider.requests.get", side_effect=exc)
        r = get(client, admin_headers, url)
        assert r.status_code == 200 and r.json["status"] == "unreachable"
        assert r.json["health_check"]["message"] == type(exc).__name__
        assert r.json["health_check"]["status_code"] is None and isinstance(r.json["health_check"]["latency_ms"], int)


def test_dataset_connection_failures_are_reported_not_500(
    client, admin_headers, k8s_client, mock_connection_checks, project, assigned_dataset, global_dataset
):
    global_dataset.host, global_dataset.port, global_dataset.type = "127.0.0.1", 1, "postgres"
    db.session.commit()
    url = f"/global/datasets/{global_dataset.id}/healthcheck"
    mock_connection_checks["dataset"].return_value = partial(Dataset._connection_check, "postgres", "127.0.0.1", 1, "db", "u", "p")
    r = get(client, admin_headers, url)
    assert r.status_code == 200 and r.json["status"] == "unreachable"
    assert r.json["health_check"]["message"] and "p@" not in r.json["health_check"]["message"]  # no credentials leak

    mock_connection_checks["dataset"].return_value = partial(Dataset._connection_check, "oracle", "h", 1, "d", "u", "p")
    r = get(client, admin_headers, url)
    assert r.json["status"] == "error" and "cannot be checked" in r.json["health_check"]["message"]

    # the failure shows in the global aggregate and in the project resource, which stays active
    mock_connection_checks["dataset"].return_value = bad(ConnectionStatus.ERROR, "password authentication failed")
    assert get(client, admin_headers, "/global/healthcheck").json["status"] == "error"
    resource = get(client, admin_headers, f"/projects/{project.id}/datasets/{global_dataset.id}/healthcheck")
    assert resource.status_code == 200 and resource.json["active"] is True
    assert resource.json["dataset"]["health_check"]["message"] == "password authentication failed"


def test_network_exception_is_in_global_and_project_aggregate(
    client, admin_headers, k8s_client, mock_connection_checks, mocker, project, assigned_trigger_repo, assigned_results_repo
):
    mocker.patch("app.models.git_provider.requests.get", side_effect=requests.Timeout("slow"))
    real_repo_check(mock_connection_checks)
    g = get(client, admin_headers, "/global/healthcheck")
    assert g.status_code == 200 and g.json["status"] == "error"
    assert g.json["trigger_repositories"][0]["status"] == g.json["results_repositories"][0]["status"] == "unreachable"
    p = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert p.status_code == 200 and p.json["status"] == "error"
    assert p.json["trigger_repositories"][0]["status"] == p.json["results_repository"]["status"] == "unreachable"


# ---------- project aggregate ----------

def test_project_healthcheck_ok_shape(
    client, admin_headers, k8s_client, mock_connection_checks, project, global_trigger_repo, pr_trigger,
    assigned_trigger_repo, assigned_results_repo, global_results_repo
):
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.status_code == 200 and r.json["status"] == "ok"
    assert set(r.json) == {"id", "name", "enabled", "status", "results_repository", "trigger_repositories"}
    assert (r.json["id"], r.json["name"]) == (project.id, "TestProject")
    item = r.json["trigger_repositories"][0]
    assert item["id"] == global_trigger_repo.id and item["pr_count"] == 1
    assert set(item) == {"id", "uri", "provider", "pr_count", "status", "health_check"}
    assert r.json["results_repository"]["id"] == global_results_repo.id
    assert r.json["results_repository"]["target_dir"] == "results"


def test_project_without_trigger_resource_is_error(
    client, admin_headers, k8s_client, mock_connection_checks, project, other_project, assigned_results_repo
):
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")  # ok needs at least one trigger repository
    assert r.status_code == 200 and r.json["status"] == "error"
    assert r.json["trigger_repositories"] == [] and r.json["results_repository"]["status"] == "ok"
    # another project's resources are not counted; no resources at all is error too
    r = get(client, admin_headers, f"/projects/{other_project.id}/healthcheck")
    assert r.json["status"] == "error" and r.json["trigger_repositories"] == [] and r.json["results_repository"] is None
    assert get(client, admin_headers, "/projects/99999/healthcheck").status_code == 404


def test_project_aggregate_error_when_a_resource_fails(
    client, admin_headers, k8s_client, mock_connection_checks, project, assigned_trigger_repo, assigned_results_repo,
    global_results_repo
):
    # trigger resource is prepared first, then results
    mock_connection_checks["repository"].side_effect = [OK, bad(ConnectionStatus.UNAUTHORIZED, "Bad credentials", 401)]
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.json["status"] == "error" and r.json["trigger_repositories"][0]["status"] == "ok"
    assert r.json["results_repository"]["status"] == "unauthorized"
    assert r.json["results_repository"]["health_check"]["status_code"] == 401

    mock_connection_checks["repository"].side_effect = [bad(ConnectionStatus.UNREACHABLE, "ConnectionError"), OK]
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.json["status"] == "error" and r.json["trigger_repositories"][0]["status"] == "unreachable"
    assert r.json["results_repository"]["status"] == "ok"


# ---------- per-resource healthchecks ----------

def test_resource_healthcheck_shapes_and_flags(
    client, admin_headers, k8s_client, mock_connection_checks, project, assigned_dataset, assigned_secret,
    assigned_trigger_repo, assigned_results_repo, global_dataset, global_trigger_repo, global_results_repo
):
    pid = project.id
    urls = {
        "dataset": f"/projects/{pid}/datasets/{global_dataset.id}/healthcheck",
        "secret": f"/projects/{pid}/secrets/test-creds/healthcheck",
        "trigger_repository": f"/projects/{pid}/repositories/triggers/{global_trigger_repo.id}/healthcheck",
        "results_repository": f"/projects/{pid}/repositories/results/{global_results_repo.id}/healthcheck",
    }
    common = {"project_id", "enabled", "revoked", "active"}
    extra = {"trigger_repository": {"pr_count"}, "results_repository": {"owned_by_federated_node", "target_dir"}}
    for key, url in urls.items():
        body = get(client, admin_headers, url).json
        assert set(body) == common | {key} | extra.get(key, set()), key
        assert body["active"] is True and body["project_id"] == pid and body[key]["status"] == "ok"
    assert get(client, admin_headers, urls["results_repository"]).json["results_repository"]["id"] == global_results_repo.id

    # a revoked resource is inactive but still checked
    assert client.patch(f"/projects/{pid}/datasets/{global_dataset.id}", json={"revoked": True}, headers=admin_headers).status_code == 200
    body = get(client, admin_headers, urls["dataset"]).json
    assert (body["revoked"], body["active"], body["enabled"], body["dataset"]["status"]) == (True, False, True, "ok")

    assert client.patch(f"/projects/{pid}/secrets/test-creds", json={"revoked": True}, headers=admin_headers).status_code == 200
    assert get(client, admin_headers, urls["secret"]).json["revoked"] is True

    # failures and missing secret keys appear in the resource body, with a 200
    mock_connection_checks["repository"].return_value = bad(ConnectionStatus.UNAUTHORIZED, "Bad credentials", 401)
    for key in ("trigger_repository", "results_repository"):
        r = get(client, admin_headers, urls[key])
        assert r.status_code == 200 and r.json[key]["status"] == "unauthorized"
    set_secret_data(k8s_client, {"USERNAME": "YQ=="})
    body = get(client, admin_headers, urls["secret"]).json
    assert body["secret"]["status"] == "secret_missing" and "TOKEN" in body["secret"]["missing_keys"]


def test_resource_healthchecks_404(
    client, admin_headers, k8s_client, mock_connection_checks, project, other_project, assigned_trigger_repo,
    global_dataset, global_secret, global_trigger_repo, global_results_repo
):
    pid, oid = project.id, other_project.id
    urls = [
        # the project has no such resource (also: assigned to another project only)
        f"/projects/{pid}/datasets/{global_dataset.id}/healthcheck",
        f"/projects/{pid}/secrets/test-creds/healthcheck",
        f"/projects/{pid}/repositories/results/{global_results_repo.id}/healthcheck",
        f"/projects/{oid}/repositories/triggers/{global_trigger_repo.id}/healthcheck",
        f"/projects/{pid}/repositories/results/{global_trigger_repo.id}/healthcheck",  # a trigger id is not a results id
        # unknown ids and projects
        f"/projects/{pid}/datasets/999/healthcheck", f"/projects/{pid}/secrets/nope/healthcheck",
        f"/projects/{pid}/repositories/triggers/999/healthcheck", "/projects/99999/datasets/1/healthcheck",
        # unknown global resources
        "/global/datasets/999/healthcheck", "/global/secrets/nope/healthcheck",
        "/global/repositories/triggers/999/healthcheck", "/global/repositories/results/999/healthcheck",
    ]
    for url in urls:
        assert get(client, admin_headers, url).status_code == 404, url
