import base64
import json

import pytest
from kubernetes.client.exceptions import ApiException

from app.helpers.const import DEFAULT_NAMESPACE
from app.models.extras.audit import Audit
from app.models.k8s_secret import K8sSecret
from app.models.trigger_repository import TriggerRepository

TOKEN = "abc123"


def encoded(value):
    return base64.b64encode(value.encode()).decode()


def cluster_error(status):
    """The body shape KubernetesException parses."""
    error = ApiException(status=status)
    error.body = json.dumps({"code": status, "details": {"causes": [{"message": "boom"}]}})
    return error


@pytest.fixture
def audited(mock_kc_client, admin_user_uuid):
    """POST, PATCH and DELETE are audited, which looks the caller up in Keycloak."""
    mock_kc_client["wrappers_kc"].return_value.get_user_by_email.return_value["id"] = admin_user_uuid


@pytest.fixture
def k8s_secret(client, k8s_client):
    secret = K8sSecret(name="gitea-token")
    secret.add()
    return secret


@pytest.fixture
def repository(client, project, k8s_secret):
    repo = TriggerRepository(
        uri="gitea.fn.svc:3000/org/repo",
        provider="gitea",
        api_uri="http://gitea.fn.svc:3000/api/v1",
        k8s_secret_name=k8s_secret.name,
        watch_dir="",
        project_id=project.id,
    )
    repo.add()
    return repo


class TestGetK8sSecrets:
    def test_list_empty(self, client, simple_admin_header):
        response = client.get("/k8s_secrets", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list(self, client, simple_admin_header, k8s_secret):
        response = client.get("/k8s_secrets", headers=simple_admin_header)
        assert response.status_code == 200
        assert [s["name"] for s in response.json] == ["gitea-token"]

    def test_get_by_id(self, client, simple_admin_header, k8s_secret):
        response = client.get(f"/k8s_secrets/{k8s_secret.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert set(response.json) == {"id", "name", "created_at", "updated_at"}
        assert response.json["name"] == "gitea-token"

    def test_get_not_found(self, client, simple_admin_header):
        assert client.get("/k8s_secrets/999", headers=simple_admin_header).status_code == 404

    def test_requires_auth(self, client):
        assert client.get("/k8s_secrets").status_code == 401


class TestPostK8sSecret:
    def test_create(self, client, k8s_client, audited, post_json_admin_header):
        response = client.post(
            "/k8s_secrets",
            data=json.dumps({"name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json
        assert response.json["name"] == "gitea-token"
        assert K8sSecret.query.filter_by(name="gitea-token").one_or_none() is not None

    def test_response_never_contains_the_values(self, client, k8s_client, audited, post_json_admin_header):
        response = client.post(
            "/k8s_secrets",
            data=json.dumps({"name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert set(response.json) == {"id", "name", "created_at", "updated_at"}
        assert TOKEN not in response.text

    def test_values_go_to_the_release_namespace_only(self, client, k8s_client, audited, post_json_admin_header):
        client.post(
            "/k8s_secrets",
            data=json.dumps({"name": "gitea-token", "values": {"TOKEN": TOKEN, "USER": "admin"}}),
            headers=post_json_admin_header
        )
        create = k8s_client["create_namespaced_secret_mock"]
        create.assert_called_once()
        assert create.call_args.args[0] == DEFAULT_NAMESPACE
        body = create.call_args.kwargs["body"]
        assert body.metadata["name"] == "gitea-token"
        assert body.data == {"TOKEN": encoded(TOKEN), "USER": encoded("admin")}

    def test_duplicate_name_conflicts(self, client, k8s_client, audited, post_json_admin_header, k8s_secret):
        response = client.post(
            "/k8s_secrets",
            data=json.dumps({"name": k8s_secret.name, "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 409
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    @pytest.mark.parametrize("name", ["", "Bad_Name", "-x", "x" * 254])
    def test_invalid_name(self, client, k8s_client, audited, post_json_admin_header, name):
        response = client.post(
            "/k8s_secrets",
            data=json.dumps({"name": name, "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    @pytest.mark.parametrize("values", [
        None, {}, "TOKEN", ["TOKEN"], {"": "x"}, {"bad key": "x"}, {"TOKEN": ""}, {"TOKEN": 5},
    ])
    def test_invalid_values(self, client, k8s_client, audited, post_json_admin_header, values):
        response = client.post(
            "/k8s_secrets",
            data=json.dumps({"name": "gitea-token", "values": values}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()
        assert K8sSecret.query.count() == 0

    def test_cluster_failure_leaves_no_row(self, client, k8s_client, audited, post_json_admin_header):
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(500)
        response = client.post(
            "/k8s_secrets",
            data=json.dumps({"name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        assert K8sSecret.query.count() == 0

    def test_existing_cluster_secret_is_overwritten(self, client, k8s_client, audited, post_json_admin_header):
        """Registering a secret decides its content, so an old one in the cluster gives way."""
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(409)
        response = client.post(
            "/k8s_secrets",
            data=json.dumps({"name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        patch = k8s_client["patch_namespaced_secret_mock"]
        patch.assert_called_once()
        assert patch.call_args.kwargs["body"].data == {"TOKEN": encoded(TOKEN)}

    def test_values_are_redacted_in_the_audit_entry(self, client, k8s_client, audited, post_json_admin_header):
        client.post(
            "/k8s_secrets",
            data=json.dumps({"name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        entry = Audit.query.filter_by(api_function="post_k8s_secret").one()
        assert TOKEN not in entry.details
        assert "*****" in entry.details

    def test_requires_auth(self, client):
        response = client.post(
            "/k8s_secrets",
            data=json.dumps({"name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401


class TestPatchK8sSecret:
    def test_rotate(self, client, k8s_client, audited, post_json_admin_header, k8s_secret):
        response = client.patch(
            f"/k8s_secrets/{k8s_secret.id}",
            data=json.dumps({"values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["name"] == "gitea-token"
        body = k8s_client["create_namespaced_secret_mock"].call_args.kwargs["body"]
        assert body.data == {"TOKEN": encoded("rotated")}

    def test_rotation_patches_an_existing_cluster_secret(self, client, k8s_client, audited, post_json_admin_header, k8s_secret):
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(409)
        response = client.patch(
            f"/k8s_secrets/{k8s_secret.id}",
            data=json.dumps({"values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        body = k8s_client["patch_namespaced_secret_mock"].call_args.kwargs["body"]
        assert body.data == {"TOKEN": encoded("rotated")}

    def test_name_cannot_change(self, client, k8s_client, audited, post_json_admin_header, k8s_secret):
        client.patch(
            f"/k8s_secrets/{k8s_secret.id}",
            data=json.dumps({"name": "another", "values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert K8sSecret.get_by_id(k8s_secret.id).name == "gitea-token"

    @pytest.mark.parametrize("body", [{}, {"values": {}}, {"values": {"TOKEN": ""}}])
    def test_invalid_values(self, client, k8s_client, audited, post_json_admin_header, k8s_secret, body):
        response = client.patch(
            f"/k8s_secrets/{k8s_secret.id}", data=json.dumps(body), headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_not_found(self, client, k8s_client, audited, post_json_admin_header):
        response = client.patch(
            "/k8s_secrets/999", data=json.dumps({"values": {"TOKEN": TOKEN}}), headers=post_json_admin_header
        )
        assert response.status_code == 404


class TestDeleteK8sSecret:
    def test_delete(self, client, k8s_client, audited, simple_admin_header, k8s_secret):
        response = client.delete(f"/k8s_secrets/{k8s_secret.id}", headers=simple_admin_header)
        assert response.status_code == 204
        assert K8sSecret.query.count() == 0
        k8s_client["delete_namespaced_secret_mock"].assert_called_once_with("gitea-token", DEFAULT_NAMESPACE)

    def test_refused_while_a_repository_uses_it(self, client, k8s_client, audited, simple_admin_header, repository):
        response = client.delete(f"/k8s_secrets/{repository.k8s_secret.id}", headers=simple_admin_header)
        assert response.status_code == 409
        assert K8sSecret.query.count() == 1
        k8s_client["delete_namespaced_secret_mock"].assert_not_called()

    def test_a_secret_shared_by_two_repositories_stays_until_both_are_gone(
        self, client, k8s_client, audited, simple_admin_header, repository, project
    ):
        second = TriggerRepository(
            uri="gitea.fn.svc:3000/org/other", provider="gitea", api_uri="http://gitea.fn.svc:3000/api/v1",
            k8s_secret_name=repository.k8s_secret_name, watch_dir="", project_id=project.id,
        )
        second.add()
        secret_id = repository.k8s_secret.id

        repository.delete()
        assert client.delete(f"/k8s_secrets/{secret_id}", headers=simple_admin_header).status_code == 409

        second.delete()
        assert client.delete(f"/k8s_secrets/{secret_id}", headers=simple_admin_header).status_code == 204

    def test_missing_cluster_secret_is_fine(self, client, k8s_client, audited, simple_admin_header, k8s_secret):
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=404)
        response = client.delete(f"/k8s_secrets/{k8s_secret.id}", headers=simple_admin_header)
        assert response.status_code == 204
        assert K8sSecret.query.count() == 0

    def test_cluster_failure_keeps_the_row(self, client, k8s_client, audited, simple_admin_header, k8s_secret):
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=500)
        response = client.delete(f"/k8s_secrets/{k8s_secret.id}", headers=simple_admin_header)
        assert response.status_code == 400
        assert K8sSecret.query.count() == 1

    def test_not_found(self, client, k8s_client, audited, simple_admin_header):
        assert client.delete("/k8s_secrets/999", headers=simple_admin_header).status_code == 404


class TestRepositoryReference:
    def test_a_repository_needs_an_existing_secret(self, client, k8s_client, simple_admin_header, post_json_admin_header, project):
        response = client.post(
            "/trigger_repositories",
            data=json.dumps({
                "uri": "http://gitea.fn.svc:3000/org/repo", "project_id": project.id, "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "k8s_secret_name": "missing",
            }),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "does not exist" in response.json["error"]

    def test_a_repository_can_reference_a_secret(self, client, k8s_client, post_json_admin_header, project, k8s_secret):
        response = client.post(
            "/trigger_repositories",
            data=json.dumps({
                "uri": "http://gitea.fn.svc:3000/org/repo", "project_id": project.id, "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "k8s_secret_name": k8s_secret.name,
            }),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json
        assert response.json["k8s_secret_name"] == "gitea-token"
        assert response.json["provider"] == "gitea"
