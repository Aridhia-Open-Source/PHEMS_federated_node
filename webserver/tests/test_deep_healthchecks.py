"""Deep tests of the healthcheck routes (ADR 0019 section 11). A failed check is reported in the body with a 200."""
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

STATUSES = {s.value for s in ConnectionStatus}
HEALTH_CHECK_KEYS = {"message", "status_code", "latency_ms"}


def get(client, admin_headers, url):
    return client.get(url, headers=admin_headers, json={})


def fail(mock_connection_checks, kind, status, message="boom", code=None):
    mock_connection_checks[kind].return_value = lambda: ConnectionCheck(status, message, code)


def set_secret_data(k8s_client, data):
    k8s_client["read_namespaced_secret_mock"].return_value.data = data


def fake_response(status_code, body=None, reason="Reason"):
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.reason = reason
    response.json.return_value = body
    return response


def use_real_repo_check(mocker, mock_connection_checks, repo_id=None):
    """Run the real GitRepositoryMixin._request_check (requests.get must be patched by the caller)."""
    mock_connection_checks["repository"].return_value = partial(
        GitRepositoryMixin._request_check, "https://api.example/repos/x", "tok"
    )


# ---------- global aggregate ----------

def test_global_healthcheck_empty_is_ok_with_all_keys(client, admin_headers, k8s_client, mock_connection_checks):
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "ok"
    assert r.json["datasets"] == []
    assert r.json["secrets"] == []
    assert r.json["trigger_repositories"] == []
    assert r.json["results_repositories"] == []


def test_global_healthcheck_shape_is_stable(client, admin_headers, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo, global_results_repo):
    r = get(client, admin_headers, "/global/healthcheck")
    assert set(r.json) == {"status", "datasets", "secrets", "trigger_repositories", "results_repositories"}
    assert set(r.json["datasets"][0]) >= {"id", "name", "host", "port", "type", "enabled", "status", "health_check"}
    assert set(r.json["secrets"][0]) >= {"label", "provider", "enabled", "status", "health_check", "keys", "missing_keys"}
    for kind in ("trigger_repositories", "results_repositories"):
        assert set(r.json[kind][0]) >= {"id", "uri", "provider", "enabled", "status", "health_check"}
    for kind in ("datasets", "secrets", "trigger_repositories", "results_repositories"):
        assert set(r.json[kind][0]["health_check"]) == HEALTH_CHECK_KEYS


def test_global_healthcheck_dataset_failure_only(client, admin_headers, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo, global_results_repo):
    fail(mock_connection_checks, "dataset", ConnectionStatus.UNREACHABLE, "refused")
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    assert r.json["datasets"][0]["status"] == "unreachable"
    assert r.json["datasets"][0]["health_check"]["message"] == "refused"
    assert r.json["trigger_repositories"][0]["status"] == "ok"
    assert r.json["results_repositories"][0]["status"] == "ok"


def test_global_healthcheck_secret_missing_makes_aggregate_error(client, admin_headers, k8s_client, mock_connection_checks, global_trigger_repo):
    k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=404)
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    assert r.json["secrets"][0]["status"] == "secret_missing"


def test_global_healthcheck_partial_failure_among_repositories(client, admin_headers, k8s_client, mock_connection_checks, global_trigger_repo, make_trigger_repo, global_results_repo):
    second = make_trigger_repo(uri="github.com/org/second")
    ok = lambda: ConnectionCheck(ConnectionStatus.OK, "OK")
    bad = lambda: ConnectionCheck(ConnectionStatus.NOT_FOUND, "Not Found", 404)
    # the first trigger repository is prepared first, then the second, then the results one
    mock_connection_checks["repository"].side_effect = [ok, bad, ok]
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    triggers = r.json["trigger_repositories"]
    assert [t["id"] for t in triggers] == [global_trigger_repo.id, second.id]
    assert [t["status"] for t in triggers] == ["ok", "not_found"]
    assert triggers[1]["health_check"]["status_code"] == 404
    assert r.json["results_repositories"][0]["status"] == "ok"


@pytest.mark.parametrize("status", ["unauthorized", "not_found", "unreachable", "secret_missing", "error"])
def test_every_failure_status_is_reported_verbatim(client, admin_headers, k8s_client, mock_connection_checks, global_trigger_repo, status):
    fail(mock_connection_checks, "repository", ConnectionStatus(status), "msg", 418)
    r = get(client, admin_headers, f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == status
    assert r.json["health_check"] == {"message": "msg", "status_code": 418, "latency_ms": None}


def test_disabled_resources_are_still_checked_and_flagged(client, admin_headers, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo, global_results_repo):
    global_dataset.enabled = False
    global_trigger_repo.enabled = False
    global_results_repo.enabled = False
    db.session.commit()
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "ok"
    assert r.json["datasets"][0]["enabled"] is False
    assert r.json["trigger_repositories"][0]["enabled"] is False
    assert r.json["results_repositories"][0]["enabled"] is False
    assert r.json["datasets"][0]["status"] == "ok"


def test_disabled_secret_is_flagged(client, admin_headers, k8s_client, mock_connection_checks, global_secret):
    global_secret.enabled = False
    db.session.commit()
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.status_code == 200
    assert r.json["enabled"] is False


# ---------- secrets ----------

def test_secret_ok_has_keys_and_no_missing_keys(client, admin_headers, k8s_client, mock_connection_checks, global_secret):
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "ok"
    assert r.json["missing_keys"] == []
    assert r.json["keys"] == sorted(["USERNAME", "PASSWORD", "USER", "TOKEN"])
    assert r.json["label"] == "test-creds"


def test_secret_never_exposes_values(client, admin_headers, k8s_client, mock_connection_checks, global_secret, global_trigger_repo):
    set_secret_data(k8s_client, {"TOKEN": "c3VwZXJzZWNyZXQ="})
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert "c3VwZXJzZWNyZXQ=" not in r.get_data(as_text=True)
    assert "supersecret" not in r.get_data(as_text=True)


def test_secret_used_by_repository_without_token_is_missing(client, admin_headers, k8s_client, mock_connection_checks, global_trigger_repo):
    set_secret_data(k8s_client, {"USERNAME": "YQ==", "PASSWORD": "Yg=="})
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "secret_missing"
    assert r.json["missing_keys"] == ["TOKEN"]
    assert "TOKEN" in r.json["health_check"]["message"]


def test_secret_used_by_dataset_needs_username_and_password(client, admin_headers, k8s_client, mock_connection_checks, global_dataset):
    set_secret_data(k8s_client, {"TOKEN": "YQ=="})
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "secret_missing"
    assert r.json["missing_keys"] == ["PASSWORD", "USERNAME"]


def test_secret_only_missing_password_is_reported(client, admin_headers, k8s_client, mock_connection_checks, global_dataset):
    set_secret_data(k8s_client, {"USERNAME": "YQ=="})
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.json["missing_keys"] == ["PASSWORD"]
    assert r.json["keys"] == ["USERNAME"]


def test_unused_secret_needs_no_particular_key(client, admin_headers, k8s_client, mock_connection_checks, global_secret):
    set_secret_data(k8s_client, {"SOMETHING": "YQ=="})
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "ok"
    assert r.json["missing_keys"] == []


def test_secret_absent_from_store_has_no_keys(client, admin_headers, k8s_client, mock_connection_checks, global_secret):
    k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=404)
    r = get(client, admin_headers, "/global/secrets/test-creds/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "secret_missing"
    assert r.json["keys"] == []
    assert "not in its store" in r.json["health_check"]["message"]


def test_repository_check_secret_missing_token_in_body(client, admin_headers, k8s_client, mock_connection_checks, mocker, global_trigger_repo):
    mocker.patch.object(GitRepositoryMixin, "prepare_connection_check", _REAL_REPO_PREPARE)
    set_secret_data(k8s_client, {"USERNAME": "YQ==", "PASSWORD": "Yg=="})
    r = get(client, admin_headers, f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "secret_missing"
    assert "TOKEN" in r.json["health_check"]["message"]


def test_repository_check_secret_not_found_in_cluster(client, admin_headers, k8s_client, mock_connection_checks, mocker, global_results_repo):
    mocker.patch.object(GitRepositoryMixin, "prepare_connection_check", _REAL_REPO_PREPARE)
    k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=404)
    r = get(client, admin_headers, f"/global/repositories/results/{global_results_repo.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "secret_missing"
    assert r.json["health_check"]["status_code"] is None


def test_repository_check_secret_data_none_is_secret_missing(client, admin_headers, k8s_client, mock_connection_checks, mocker, global_trigger_repo):
    mocker.patch.object(GitRepositoryMixin, "prepare_connection_check", _REAL_REPO_PREPARE)
    set_secret_data(k8s_client, None)
    r = get(client, admin_headers, f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "secret_missing"


def test_dataset_check_missing_credentials_is_secret_missing(client, admin_headers, k8s_client, mock_connection_checks, mocker, global_dataset):
    mocker.patch.object(Dataset, "prepare_connection_check", _REAL_DATASET_PREPARE)
    set_secret_data(k8s_client, {"TOKEN": "YQ=="})
    r = get(client, admin_headers, f"/global/datasets/{global_dataset.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "secret_missing"
    assert "USERNAME" in r.json["health_check"]["message"]


# ---------- connection-check exceptions ----------

@pytest.mark.parametrize("exc", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_repository_network_exception_is_unreachable_not_500(client, admin_headers, k8s_client, mock_connection_checks, mocker, global_trigger_repo, exc):
    mocker.patch("app.models.git_repository.requests.get", side_effect=exc)
    use_real_repo_check(mocker, mock_connection_checks)
    r = get(client, admin_headers, f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "unreachable"
    assert r.json["health_check"]["message"] == type(exc).__name__
    assert r.json["health_check"]["status_code"] is None
    assert isinstance(r.json["health_check"]["latency_ms"], int)


def test_repository_network_exception_is_reported_in_global_aggregate(client, admin_headers, k8s_client, mock_connection_checks, mocker, global_trigger_repo, global_results_repo):
    mocker.patch("app.models.git_repository.requests.get", side_effect=requests.ConnectionError("down"))
    use_real_repo_check(mocker, mock_connection_checks)
    r = get(client, admin_headers, "/global/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    assert r.json["trigger_repositories"][0]["status"] == "unreachable"
    assert r.json["results_repositories"][0]["status"] == "unreachable"


@pytest.mark.parametrize("code,expected", [(200, "ok"), (401, "unauthorized"), (403, "unauthorized"), (404, "not_found"), (500, "error"), (429, "error")])
def test_repository_http_status_maps_to_status(client, admin_headers, k8s_client, mock_connection_checks, mocker, global_trigger_repo, code, expected):
    mocker.patch("app.models.git_repository.requests.get", return_value=fake_response(code, {"message": "Bad credentials"}))
    use_real_repo_check(mocker, mock_connection_checks)
    r = get(client, admin_headers, f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == expected
    assert r.json["health_check"]["status_code"] == code
    assert r.json["health_check"]["message"] == "Bad credentials"


def test_repository_non_json_error_body_falls_back_to_reason(client, admin_headers, k8s_client, mock_connection_checks, mocker, global_trigger_repo):
    response = fake_response(502, reason="Bad Gateway")
    response.json.side_effect = ValueError("no json")
    mocker.patch("app.models.git_repository.requests.get", return_value=response)
    use_real_repo_check(mocker, mock_connection_checks)
    r = get(client, admin_headers, f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    assert r.json["health_check"]["message"] == "Bad Gateway"


def test_dataset_connection_refused_is_unreachable_not_500(client, admin_headers, k8s_client, mock_connection_checks, global_dataset):
    global_dataset.host = "127.0.0.1"
    global_dataset.port = 1
    global_dataset.type = "postgres"
    db.session.commit()
    mock_connection_checks["dataset"].return_value = partial(
        Dataset._connection_check, "postgres", "127.0.0.1", 1, "db", "u", "p"
    )
    r = get(client, admin_headers, f"/global/datasets/{global_dataset.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "unreachable"
    assert r.json["health_check"]["message"]
    assert "p@" not in r.json["health_check"]["message"]


def test_dataset_unsupported_engine_is_error_in_body(client, admin_headers, k8s_client, mock_connection_checks, global_dataset):
    mock_connection_checks["dataset"].return_value = partial(Dataset._connection_check, "oracle", "h", 1, "d", "u", "p")
    r = get(client, admin_headers, f"/global/datasets/{global_dataset.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    assert "cannot be checked" in r.json["health_check"]["message"]


def test_dataset_failure_is_reported_in_global_aggregate_and_link(client, admin_headers, k8s_client, mock_connection_checks, project, linked_dataset, global_dataset):
    fail(mock_connection_checks, "dataset", ConnectionStatus.ERROR, "password authentication failed")
    g = get(client, admin_headers, "/global/healthcheck")
    assert g.json["status"] == "error"
    assert g.json["datasets"][0]["status"] == "error"
    link = get(client, admin_headers, f"/projects/{project.id}/datasets/{global_dataset.id}/healthcheck")
    assert link.status_code == 200
    assert link.json["dataset"]["status"] == "error"
    assert link.json["dataset"]["health_check"]["message"] == "password authentication failed"
    assert link.json["active"] is True


# ---------- project aggregate ----------

def test_project_healthcheck_shape_keys_always_present(client, admin_headers, k8s_client, mock_connection_checks, project):
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.status_code == 200
    assert set(r.json) == {"id", "name", "enabled", "status", "results_repository", "trigger_repositories"}
    assert r.json["id"] == project.id
    assert r.json["name"] == "TestProject"
    assert r.json["enabled"] is False


def test_project_with_only_trigger_link_is_ok(client, admin_headers, k8s_client, mock_connection_checks, project, linked_trigger_repo, global_trigger_repo):
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.json["status"] == "ok"
    assert r.json["results_repository"] is None
    item = r.json["trigger_repositories"][0]
    assert item["id"] == global_trigger_repo.id
    assert item["pr_count"] == 0
    assert set(item) == {"id", "uri", "provider", "pr_count", "status", "health_check"}


def test_project_with_only_results_link_is_error(client, admin_headers, k8s_client, mock_connection_checks, project, linked_results_repo):
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["trigger_repositories"] == []
    assert r.json["results_repository"]["status"] == "ok"
    # ok needs at least one trigger repository
    assert r.json["status"] == "error"


def test_project_results_repository_failure_makes_aggregate_error(client, admin_headers, k8s_client, mock_connection_checks, project, linked_trigger_repo, linked_results_repo, global_results_repo):
    ok = lambda: ConnectionCheck(ConnectionStatus.OK, "OK")
    bad = lambda: ConnectionCheck(ConnectionStatus.UNAUTHORIZED, "Bad credentials", 401)
    mock_connection_checks["repository"].side_effect = [ok, bad]  # trigger link first, then results
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    assert r.json["trigger_repositories"][0]["status"] == "ok"
    assert r.json["results_repository"]["status"] == "unauthorized"
    assert r.json["results_repository"]["id"] == global_results_repo.id
    assert r.json["results_repository"]["health_check"]["status_code"] == 401


def test_project_trigger_failure_makes_aggregate_error(client, admin_headers, k8s_client, mock_connection_checks, project, linked_trigger_repo, linked_results_repo):
    ok = lambda: ConnectionCheck(ConnectionStatus.OK, "OK")
    bad = lambda: ConnectionCheck(ConnectionStatus.UNREACHABLE, "ConnectionError")
    mock_connection_checks["repository"].side_effect = [bad, ok]
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.json["status"] == "error"
    assert r.json["trigger_repositories"][0]["status"] == "unreachable"
    assert r.json["results_repository"]["status"] == "ok"


def test_project_partial_failure_among_several_trigger_links(client, admin_headers, k8s_client, mock_connection_checks, project, linked_trigger_repo, make_trigger_repo, global_trigger_repo):
    second = make_trigger_repo(uri="github.com/org/second")
    r = client.put(f"/projects/{project.id}/repositories/triggers/{second.id}", json={"watch_dir": "other"}, headers=admin_headers)
    assert r.status_code == 201
    ok = lambda: ConnectionCheck(ConnectionStatus.OK, "OK")
    bad = lambda: ConnectionCheck(ConnectionStatus.NOT_FOUND, "Not Found", 404)
    mock_connection_checks["repository"].side_effect = [ok, bad]
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    assert len(r.json["trigger_repositories"]) == 2
    assert sorted(t["status"] for t in r.json["trigger_repositories"]) == ["not_found", "ok"]


def test_project_aggregate_network_exception_is_in_body(client, admin_headers, k8s_client, mock_connection_checks, mocker, project, linked_trigger_repo, linked_results_repo):
    mocker.patch("app.models.git_repository.requests.get", side_effect=requests.Timeout("slow"))
    use_real_repo_check(mocker, mock_connection_checks)
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["status"] == "error"
    assert r.json["trigger_repositories"][0]["status"] == "unreachable"
    assert r.json["results_repository"]["status"] == "unreachable"


def test_project_aggregate_counts_pull_requests_per_link(client, admin_headers, k8s_client, mock_connection_checks, project, global_trigger_repo, pr_trigger):
    r = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert r.json["trigger_repositories"][0]["pr_count"] == 1


def test_project_aggregate_isolated_from_other_projects_links(client, admin_headers, k8s_client, mock_connection_checks, project, other_project, linked_trigger_repo, linked_results_repo):
    r = get(client, admin_headers, f"/projects/{other_project.id}/healthcheck")
    assert r.status_code == 200
    assert r.json["trigger_repositories"] == []
    assert r.json["results_repository"] is None
    assert r.json["id"] == other_project.id


def test_project_healthcheck_unknown_project_404(client, admin_headers, k8s_client, mock_connection_checks):
    assert get(client, admin_headers, "/projects/99999/healthcheck").status_code == 404


def test_project_aggregate_with_revoked_trigger_link(client, admin_headers, k8s_client, mock_connection_checks, project, linked_trigger_repo, global_trigger_repo):
    # Current behaviour (asserted, ADR is silent): a revoked link is still listed and checked
    # in the project aggregate; its state is visible on the per-link healthcheck.
    r = client.patch(f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}", json={"revoked": True}, headers=admin_headers)
    assert r.status_code == 200
    agg = get(client, admin_headers, f"/projects/{project.id}/healthcheck")
    assert agg.status_code == 200
    assert set(agg.json) == {"id", "name", "enabled", "status", "results_repository", "trigger_repositories"}
    link = get(client, admin_headers, f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    assert link.json["revoked"] is True
    assert link.json["active"] is False


# ---------- per-link healthchecks ----------

def test_link_healthcheck_shapes(client, admin_headers, k8s_client, mock_connection_checks, project, linked_dataset, linked_secret, linked_trigger_repo, linked_results_repo, global_dataset, global_trigger_repo, global_results_repo):
    pid = project.id
    common = {"project_id", "enabled", "revoked", "active"}
    d = get(client, admin_headers, f"/projects/{pid}/datasets/{global_dataset.id}/healthcheck").json
    s = get(client, admin_headers, f"/projects/{pid}/secrets/test-creds/healthcheck").json
    t = get(client, admin_headers, f"/projects/{pid}/repositories/triggers/{global_trigger_repo.id}/healthcheck").json
    rr = get(client, admin_headers, f"/projects/{pid}/repositories/results/{global_results_repo.id}/healthcheck").json
    assert set(d) == common | {"dataset"}
    assert set(s) == common | {"secret"}
    assert set(t) == common | {"pr_count", "trigger_repository"}
    assert set(rr) == common | {"owned_by_federated_node", "target_dir", "results_repository"}
    assert d["dataset"]["id"] == global_dataset.id
    assert s["secret"]["label"] == "test-creds"
    assert t["trigger_repository"]["id"] == global_trigger_repo.id
    assert rr["target_dir"] == "results"
    assert rr["results_repository"]["id"] == global_results_repo.id


def test_link_healthcheck_reports_revoked_and_disabled(client, admin_headers, k8s_client, mock_connection_checks, project, linked_dataset, global_dataset):
    r = client.patch(f"/projects/{project.id}/datasets/{global_dataset.id}", json={"revoked": True}, headers=admin_headers)
    assert r.status_code == 200
    body = get(client, admin_headers, f"/projects/{project.id}/datasets/{global_dataset.id}/healthcheck").json
    assert body["revoked"] is True
    assert body["active"] is False
    assert body["enabled"] is True
    # a revoked link is still checked, and its connection status is unaffected
    assert body["dataset"]["status"] == "ok"


def test_link_healthcheck_disabled_link(client, admin_headers, k8s_client, mock_connection_checks, lock_project, linked_secret):
    project = lock_project
    r = client.patch(f"/projects/{project.id}/secrets/test-creds", json={"enabled": False}, headers=admin_headers)
    assert r.status_code == 200
    body = get(client, admin_headers, f"/projects/{project.id}/secrets/test-creds/healthcheck").json
    assert body["enabled"] is False
    assert body["active"] is False
    assert body["revoked"] is False


def test_link_healthcheck_pr_count(client, admin_headers, k8s_client, mock_connection_checks, project, global_trigger_repo, pr_trigger):
    r = get(client, admin_headers, f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    assert r.json["pr_count"] == 1


def test_link_secret_healthcheck_reports_missing_keys(client, admin_headers, k8s_client, mock_connection_checks, project, linked_secret, global_trigger_repo):
    set_secret_data(k8s_client, {"USERNAME": "YQ=="})
    r = get(client, admin_headers, f"/projects/{project.id}/secrets/test-creds/healthcheck")
    assert r.status_code == 200
    assert r.json["secret"]["status"] == "secret_missing"
    assert r.json["secret"]["missing_keys"] == ["TOKEN"]
    assert r.json["active"] is True


def test_link_repository_failure_in_body(client, admin_headers, k8s_client, mock_connection_checks, project, linked_trigger_repo, linked_results_repo, global_trigger_repo, global_results_repo):
    fail(mock_connection_checks, "repository", ConnectionStatus.UNAUTHORIZED, "Bad credentials", 401)
    t = get(client, admin_headers, f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}/healthcheck")
    rr = get(client, admin_headers, f"/projects/{project.id}/repositories/results/{global_results_repo.id}/healthcheck")
    assert t.status_code == rr.status_code == 200
    assert t.json["trigger_repository"]["status"] == "unauthorized"
    assert rr.json["results_repository"]["status"] == "unauthorized"


def test_link_healthchecks_404_when_project_has_no_link(client, admin_headers, k8s_client, mock_connection_checks, project, other_project, global_dataset, global_secret, global_trigger_repo, global_results_repo):
    pid = project.id
    urls = [
        f"/projects/{pid}/datasets/{global_dataset.id}/healthcheck",
        f"/projects/{pid}/secrets/test-creds/healthcheck",
        f"/projects/{pid}/repositories/triggers/{global_trigger_repo.id}/healthcheck",
        f"/projects/{pid}/repositories/results/{global_results_repo.id}/healthcheck",
    ]
    for url in urls:
        assert get(client, admin_headers, url).status_code == 404, url


def test_link_healthchecks_cross_project_404(client, admin_headers, k8s_client, mock_connection_checks, other_project, linked_dataset, linked_secret, linked_trigger_repo, linked_results_repo, global_dataset, global_trigger_repo, global_results_repo):
    oid = other_project.id
    urls = [
        f"/projects/{oid}/datasets/{global_dataset.id}/healthcheck",
        f"/projects/{oid}/secrets/test-creds/healthcheck",
        f"/projects/{oid}/repositories/triggers/{global_trigger_repo.id}/healthcheck",
        f"/projects/{oid}/repositories/results/{global_results_repo.id}/healthcheck",
    ]
    for url in urls:
        assert get(client, admin_headers, url).status_code == 404, url


def test_link_healthchecks_unknown_ids_404(client, admin_headers, k8s_client, mock_connection_checks, project):
    pid = project.id
    for url in [
        f"/projects/{pid}/datasets/999/healthcheck",
        f"/projects/{pid}/secrets/nope/healthcheck",
        f"/projects/{pid}/repositories/triggers/999/healthcheck",
        f"/projects/{pid}/repositories/results/999/healthcheck",
        "/projects/99999/datasets/1/healthcheck",
        "/projects/99999/secrets/test-creds/healthcheck",
    ]:
        assert get(client, admin_headers, url).status_code == 404, url


def test_global_resource_healthchecks_unknown_ids_404(client, admin_headers, k8s_client, mock_connection_checks):
    for url in [
        "/global/datasets/999/healthcheck",
        "/global/secrets/nope/healthcheck",
        "/global/repositories/triggers/999/healthcheck",
        "/global/repositories/results/999/healthcheck",
    ]:
        assert get(client, admin_headers, url).status_code == 404, url


def test_trigger_id_is_not_a_results_id(client, admin_headers, k8s_client, mock_connection_checks, project, linked_trigger_repo, global_trigger_repo):
    # the same numeric id under the other repository kind must not resolve to the trigger link
    r = get(client, admin_headers, f"/projects/{project.id}/repositories/results/{global_trigger_repo.id}/healthcheck")
    assert r.status_code == 404
