import base64
import json

import pytest
from kubernetes.client.exceptions import ApiException
from sqlalchemy.exc import IntegrityError

from app.helpers.base_model import db
from app.helpers.const import DEFAULT_NAMESPACE
from app.models.extras.audit import Audit
from app.models.secret import Secret
from app.models.secret_type import SecretType
from app.models.trigger_repository import TriggerRepository

TOKEN = "abc123"
SECRET_FIELDS = {"id", "project_id", "name", "secret_type", "store_name", "created_at", "updated_at"}


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
def secret(client, k8s_client, project):
    secret = Secret(project_id=project.id, name="gitea-token", secret_type=SecretType.K8S)
    secret.add()
    return secret


@pytest.fixture
def repository(client, project, secret):
    repo = TriggerRepository(
        uri="gitea.fn.svc:3000/org/repo",
        provider="gitea",
        api_uri="http://gitea.fn.svc:3000/api/v1",
        secret_id=secret.id,
        watch_dir="",
        project_id=project.id,
    )
    repo.add()
    return repo


class TestGetSecrets:
    def test_list_empty(self, client, simple_admin_header, project):
        response = client.get(f"/projects/{project.id}/secrets", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list_is_scoped_to_the_project(self, client, simple_admin_header, secret, other_project):
        Secret(project_id=other_project.id, name="other-token", secret_type=SecretType.K8S).add()
        response = client.get(f"/projects/{secret.project_id}/secrets", headers=simple_admin_header)
        assert [s["name"] for s in response.json] == ["gitea-token"]
        response = client.get(f"/projects/{other_project.id}/secrets", headers=simple_admin_header)
        assert [s["name"] for s in response.json] == ["other-token"]

    def test_list_unknown_project(self, client, simple_admin_header):
        assert client.get("/projects/9999/secrets", headers=simple_admin_header).status_code == 404

    def test_get_by_name(self, client, simple_admin_header, secret):
        response = client.get(f"/projects/{secret.project_id}/secrets/{secret.name}", headers=simple_admin_header)
        assert response.status_code == 200
        assert set(response.json) == SECRET_FIELDS
        assert response.json["name"] == "gitea-token"
        assert response.json["secret_type"] == "K8S"
        assert response.json["store_name"] == f"{secret.project_id}-gitea-token"

    def test_get_not_found(self, client, simple_admin_header, project):
        assert client.get(f"/projects/{project.id}/secrets/missing", headers=simple_admin_header).status_code == 404

    def test_get_in_another_project_is_not_found(self, client, simple_admin_header, secret, other_project):
        response = client.get(f"/projects/{other_project.id}/secrets/{secret.name}", headers=simple_admin_header)
        assert response.status_code == 404

    def test_requires_auth(self, client, project):
        assert client.get(f"/projects/{project.id}/secrets").status_code == 401


class TestPostSecret:
    def test_create(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json
        assert response.json["name"] == "gitea-token"
        assert response.json["project_id"] == project.id
        assert response.json["store_name"] == f"{project.id}-gitea-token"
        assert Secret.query.filter_by(name="gitea-token").one_or_none() is not None

    def test_response_never_contains_the_values(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert set(response.json) == SECRET_FIELDS
        assert TOKEN not in response.text

    def test_values_go_to_the_release_namespace_only(self, client, k8s_client, audited, post_json_admin_header, project):
        client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN, "USER": "admin"}}),
            headers=post_json_admin_header
        )
        create = k8s_client["create_namespaced_secret_mock"]
        create.assert_called_once()
        assert create.call_args.args[0] == DEFAULT_NAMESPACE
        body = create.call_args.kwargs["body"]
        assert body.metadata["name"] == f"{project.id}-gitea-token"
        assert body.data == {"TOKEN": encoded(TOKEN), "USER": encoded("admin")}

    def test_duplicate_name_conflicts(self, client, k8s_client, audited, post_json_admin_header, secret, project):
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": secret.name, "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 409
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_same_name_in_two_projects(self, client, k8s_client, audited, post_json_admin_header, project, other_project):
        ids = []
        for proj in (project, other_project):
            response = client.post(
                f"/projects/{proj.id}/secrets",
                data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
                headers=post_json_admin_header
            )
            assert response.status_code == 201, response.json
            ids.append(response.json["store_name"])
        assert ids == [f"{project.id}-gitea-token", f"{other_project.id}-gitea-token"]
        assert Secret.query.filter_by(name="gitea-token").count() == 2

    def test_project_must_exist(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.post(
            "/projects/9999/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    @pytest.mark.parametrize("secret_type", [None, "", "VAULT"])
    def test_secret_type_must_be_a_known_store(self, client, k8s_client, audited, post_json_admin_header, project, secret_type):
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": secret_type, "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_name_must_leave_room_for_the_project_prefix(self, client, k8s_client, audited, post_json_admin_header, project):
        prefix = f"{project.id}-"
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "x" * (254 - len(prefix)), "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "x" * (253 - len(prefix)), "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json

    @pytest.mark.parametrize("name", ["", "Bad_Name", "-x", "x" * 254])
    def test_invalid_name(self, client, k8s_client, audited, post_json_admin_header, name, project):
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": name, "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    @pytest.mark.parametrize("values", [
        None, {}, "TOKEN", ["TOKEN"], {"": "x"}, {"bad key": "x"}, {"TOKEN": ""}, {"TOKEN": 5},
    ])
    def test_invalid_values(self, client, k8s_client, audited, post_json_admin_header, values, project):
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": values}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()
        assert Secret.query.count() == 0

    def test_cluster_failure_leaves_no_row(self, client, k8s_client, audited, post_json_admin_header, project):
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(500)
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        assert Secret.query.count() == 0

    def test_existing_cluster_secret_is_overwritten(self, client, k8s_client, audited, post_json_admin_header, project):
        """Registering a secret decides its content, so an old one in the cluster gives way."""
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(409)
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        patch = k8s_client["patch_namespaced_secret_mock"]
        patch.assert_called_once()
        assert patch.call_args.kwargs["body"].data == {"TOKEN": encoded(TOKEN)}

    def test_values_are_redacted_in_the_audit_entry(self, client, k8s_client, audited, post_json_admin_header, project):
        client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        entry = Audit.query.filter_by(api_function="post_secret").one()
        assert TOKEN not in entry.details
        assert "*****" in entry.details

    def test_requires_auth(self, client, project):
        response = client.post(
            f"/projects/{project.id}/secrets",
            data=json.dumps({"secret_type": "K8S", "name": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401


class TestPatchSecret:
    def test_rotate(self, client, k8s_client, audited, post_json_admin_header, secret):
        response = client.patch(
            f"/projects/{secret.project_id}/secrets/{secret.name}",
            data=json.dumps({"values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["name"] == "gitea-token"
        body = k8s_client["create_namespaced_secret_mock"].call_args.kwargs["body"]
        assert body.metadata["name"] == secret.store_name
        assert body.data == {"TOKEN": encoded("rotated")}

    def test_rotation_patches_an_existing_cluster_secret(self, client, k8s_client, audited, post_json_admin_header, secret):
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(409)
        response = client.patch(
            f"/projects/{secret.project_id}/secrets/{secret.name}",
            data=json.dumps({"values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        body = k8s_client["patch_namespaced_secret_mock"].call_args.kwargs["body"]
        assert body.data == {"TOKEN": encoded("rotated")}

    def test_name_cannot_change(self, client, k8s_client, audited, post_json_admin_header, secret):
        client.patch(
            f"/projects/{secret.project_id}/secrets/{secret.name}",
            data=json.dumps({"name": "another", "values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert Secret.get_by_id(secret.id).name == "gitea-token"

    @pytest.mark.parametrize("body", [{}, {"values": {}}, {"values": {"TOKEN": ""}}])
    def test_invalid_values(self, client, k8s_client, audited, post_json_admin_header, secret, body):
        response = client.patch(
            f"/projects/{secret.project_id}/secrets/{secret.name}", data=json.dumps(body), headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_not_found(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.patch(
            f"/projects/{project.id}/secrets/missing", data=json.dumps({"values": {"TOKEN": TOKEN}}), headers=post_json_admin_header
        )
        assert response.status_code == 404


class TestDeleteSecret:
    def test_delete(self, client, k8s_client, audited, simple_admin_header, secret):
        store_name = secret.store_name
        response = client.delete(f"/projects/{secret.project_id}/secrets/{secret.name}", headers=simple_admin_header)
        assert response.status_code == 204
        assert Secret.query.count() == 0
        k8s_client["delete_namespaced_secret_mock"].assert_called_once_with(store_name, DEFAULT_NAMESPACE)

    def test_refused_while_a_repository_uses_it(self, client, k8s_client, audited, simple_admin_header, repository):
        response = client.delete(f"/projects/{repository.project_id}/secrets/{repository.secret.name}", headers=simple_admin_header)
        assert response.status_code == 409
        assert Secret.query.count() == 1
        k8s_client["delete_namespaced_secret_mock"].assert_not_called()

    def test_a_secret_shared_by_two_repositories_stays_until_both_are_gone(
        self, client, k8s_client, audited, simple_admin_header, repository, project
    ):
        second = TriggerRepository(
            uri="gitea.fn.svc:3000/org/other", provider="gitea", api_uri="http://gitea.fn.svc:3000/api/v1",
            secret_id=repository.secret_id, watch_dir="", project_id=project.id,
        )
        second.add()

        repository.delete()
        assert client.delete(f"/projects/{project.id}/secrets/gitea-token", headers=simple_admin_header).status_code == 409

        second.delete()
        assert client.delete(f"/projects/{project.id}/secrets/gitea-token", headers=simple_admin_header).status_code == 204

    def test_missing_cluster_secret_is_fine(self, client, k8s_client, audited, simple_admin_header, secret):
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=404)
        response = client.delete(f"/projects/{secret.project_id}/secrets/{secret.name}", headers=simple_admin_header)
        assert response.status_code == 204
        assert Secret.query.count() == 0

    def test_cluster_failure_keeps_the_row(self, client, k8s_client, audited, simple_admin_header, secret):
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=500)
        response = client.delete(f"/projects/{secret.project_id}/secrets/{secret.name}", headers=simple_admin_header)
        assert response.status_code == 400
        assert Secret.query.count() == 1

    def test_not_found(self, client, k8s_client, audited, simple_admin_header, project):
        assert client.delete(f"/projects/{project.id}/secrets/missing", headers=simple_admin_header).status_code == 404


class TestRepositoryReference:
    def test_a_repository_cannot_use_another_projects_secret(
        self, client, k8s_client, post_json_admin_header, project, other_project
    ):
        secret = Secret(project_id=other_project.id, name="foreign-token", secret_type=SecretType.K8S)
        secret.add()
        response = client.post(
            "/trigger_repositories",
            data=json.dumps({
                "uri": "http://gitea.fn.svc:3000/org/repo", "project_id": project.id, "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "secret_name": "foreign-token",
            }),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "does not exist" in response.json["error"]

    def test_the_database_rejects_a_repository_pointing_at_another_projects_secret(
        self, client, k8s_client, project, other_project
    ):
        secret = Secret(project_id=other_project.id, name="foreign-token", secret_type=SecretType.K8S)
        secret.add()
        repo = TriggerRepository(
            uri="gitea.fn.svc:3000/org/repo", provider="gitea", api_uri="http://gitea.fn.svc:3000/api/v1",
            secret_id=secret.id, watch_dir="", project_id=project.id,
        )
        with pytest.raises(IntegrityError):
            repo.add()
        db.session.rollback()

    def test_the_response_names_the_cluster_secret(
        self, client, k8s_client, post_json_admin_header, project, secret
    ):
        response = client.post(
            "/trigger_repositories",
            data=json.dumps({
                "uri": "http://gitea.fn.svc:3000/org/repo", "project_id": project.id, "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "secret_name": secret.name,
            }),
            headers=post_json_admin_header
        )
        assert response.json["secret_store_name"] == f"{project.id}-gitea-token"

    def test_the_token_is_read_from_the_cluster_secret(self, client, k8s_client, repository):
        repository.get_token()
        k8s_client["read_namespaced_secret_mock"].assert_called_once_with(
            f"{repository.project_id}-gitea-token", DEFAULT_NAMESPACE
        )

    def test_a_repository_needs_an_existing_secret(self, client, k8s_client, simple_admin_header, post_json_admin_header, project):
        response = client.post(
            "/trigger_repositories",
            data=json.dumps({
                "uri": "http://gitea.fn.svc:3000/org/repo", "project_id": project.id, "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "secret_name": "missing",
            }),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "does not exist" in response.json["error"]

    def test_a_repository_can_reference_a_secret(self, client, k8s_client, post_json_admin_header, project, secret):
        response = client.post(
            "/trigger_repositories",
            data=json.dumps({
                "uri": "http://gitea.fn.svc:3000/org/repo", "project_id": project.id, "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "secret_name": secret.name,
            }),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json
        assert response.json["secret_name"] == "gitea-token"
        assert response.json["provider"] == "gitea"
