from kubernetes.client.exceptions import ApiException

from app.models.git_provider import ConnectionCheck, ConnectionStatus


def test_global_healthcheck_ok(client, admin_headers, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo, global_results_repo):
    response = client.get("/global/healthcheck", headers=admin_headers, json={})

    assert response.status_code == 200
    assert response.json["status"] == "ok"
    for key in ["datasets", "secrets", "trigger_repositories", "results_repositories"]:
        assert len(response.json[key]) == 1
        assert response.json[key][0]["status"] == "ok"


def test_global_healthcheck_reports_failure(client, admin_headers, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo, global_results_repo):
    mock_connection_checks["repository"].return_value = lambda: ConnectionCheck(ConnectionStatus.UNAUTHORIZED, "Unauthorized", 401)

    response = client.get("/global/healthcheck", headers=admin_headers, json={})

    assert response.status_code == 200
    assert response.json["status"] == "error"
    assert response.json["trigger_repositories"][0]["status"] == "unauthorized"


def test_resource_healthchecks(client, admin_headers, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo, global_results_repo):
    urls = [
        f"/global/datasets/{global_dataset.id}/healthcheck",
        "/global/secrets/test-creds/healthcheck",
        f"/global/repositories/triggers/{global_trigger_repo.id}/healthcheck",
        f"/global/repositories/results/{global_results_repo.id}/healthcheck",
    ]
    for url in urls:
        response = client.get(url, headers=admin_headers, json={})
        assert response.status_code == 200, url
        assert response.json["status"] == "ok", url


def test_resource_healthcheck_404(client, admin_headers, k8s_client, mock_connection_checks):
    response = client.get("/global/repositories/triggers/999/healthcheck", headers=admin_headers, json={})
    assert response.status_code == 404

    response = client.get("/global/secrets/nope/healthcheck", headers=admin_headers, json={})
    assert response.status_code == 404


def test_secret_missing(client, admin_headers, k8s_client, mock_connection_checks, global_trigger_repo):
    k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=404)

    response = client.get("/global/secrets/test-creds/healthcheck", headers=admin_headers, json={})

    assert response.status_code == 200
    assert response.json["status"] == "secret_missing"
    assert response.json["keys"] == []
    assert "TOKEN" in response.json["missing_keys"]


def test_project_healthcheck(client, admin_headers, k8s_client, mock_connection_checks, project, global_trigger_repo, linked_trigger_repo, linked_results_repo):
    response = client.get(f"/projects/{project.id}/healthcheck", headers=admin_headers, json={})

    assert response.status_code == 200
    assert response.json["status"] == "ok"
    assert response.json["trigger_repositories"][0]["id"] == global_trigger_repo.id
    assert response.json["results_repository"]["target_dir"] == "results"


def test_project_healthcheck_no_links_is_error(client, admin_headers, k8s_client, mock_connection_checks, other_project):
    response = client.get(f"/projects/{other_project.id}/healthcheck", headers=admin_headers, json={})

    assert response.status_code == 200
    assert response.json["status"] == "error"
    assert response.json["trigger_repositories"] == []
    assert response.json["results_repository"] is None


def test_link_healthchecks(client, admin_headers, k8s_client, mock_connection_checks, project, linked_dataset, linked_secret, linked_trigger_repo, linked_results_repo, global_dataset, global_trigger_repo, global_results_repo):
    pid = project.id
    urls = [
        f"/projects/{pid}/datasets/{global_dataset.id}/healthcheck",
        f"/projects/{pid}/secrets/test-creds/healthcheck",
        f"/projects/{pid}/repositories/triggers/{global_trigger_repo.id}/healthcheck",
        f"/projects/{pid}/repositories/results/{global_results_repo.id}/healthcheck",
    ]
    for url in urls:
        response = client.get(url, headers=admin_headers, json={})
        assert response.status_code == 200, url
        assert response.json["active"] is True, url
        assert response.json["project_id"] == pid, url


def test_link_healthcheck_other_project_404(client, admin_headers, k8s_client, mock_connection_checks, linked_trigger_repo, other_project, global_trigger_repo):
    response = client.get(
        f"/projects/{other_project.id}/repositories/triggers/{global_trigger_repo.id}/healthcheck",
        headers=admin_headers, json={},
    )
    assert response.status_code == 404
