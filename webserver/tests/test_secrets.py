import base64
import json

import pytest
from kubernetes.client.exceptions import ApiException
from sqlalchemy.exc import IntegrityError

from app.helpers.base_model import db
from app.helpers.const import DEFAULT_NAMESPACE
from app.helpers.exceptions import InvalidRequest
from app.models.extras.audit import Audit
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.trigger_repository import TriggerRepository

TOKEN = "abc123"
SECRET_FIELDS = {"id", "label", "description", "provider", "key", "namespace", "created_at", "updated_at"}


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
    secret = Secret(label="gitea-token", provider=SecretProviderType.K8S, namespace=DEFAULT_NAMESPACE)
    secret.add()
    return secret


@pytest.fixture
def repository(client, project, secret):
    repo = TriggerRepository(
        uri="gitea.fn.svc:3000/org/repo",
        provider="gitea",
        api_uri="http://gitea.fn.svc:3000/api/v1",
        secret_id=secret.id,
    )
    repo.add()
    return repo


class TestGetSecrets:
    def test_list_empty(self, client, simple_admin_header, project):
        response = client.get("/secrets", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == []

    def test_list_is_global(self, client, simple_admin_header, secret, other_project):
        Secret(label="other-token", provider=SecretProviderType.K8S).add()
        response = client.get("/secrets", headers=simple_admin_header)
        assert sorted(s["label"] for s in response.json) == ["gitea-token", "other-token"]

    def test_the_project_route_is_gone(self, client, simple_admin_header, project):
        assert client.get(f"/projects/{project.id}/secrets", headers=simple_admin_header).status_code == 404

    def test_get_by_name(self, client, simple_admin_header, secret):
        response = client.get(f"/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 200
        assert set(response.json) == SECRET_FIELDS
        assert response.json["label"] == "gitea-token"
        assert response.json["provider"] == "K8S"
        assert response.json["key"] == "fn-secret-gitea-token"

    def test_get_not_found(self, client, simple_admin_header, project):
        assert client.get("/secrets/missing", headers=simple_admin_header).status_code == 404

    def test_requires_auth(self, client, project):
        assert client.get("/secrets").status_code == 401


class TestPostSecret:
    def test_create(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json
        assert response.json["label"] == "gitea-token"
        assert response.json["provider"] == "K8S"
        assert response.json["key"] == "fn-secret-gitea-token"
        assert response.json["namespace"] == DEFAULT_NAMESPACE
        assert response.json["description"] is None
        assert Secret.query.filter_by(label="gitea-token").one().namespace == DEFAULT_NAMESPACE

    def test_create_with_description(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "description": "ci token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json
        assert response.json["description"] == "ci token"

    def test_namespace_in_the_body_is_ignored(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "namespace": "evil", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.json["namespace"] == DEFAULT_NAMESPACE
        assert k8s_client["create_namespaced_secret_mock"].call_args.args[0] == DEFAULT_NAMESPACE

    def test_response_never_contains_the_values(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert set(response.json) == SECRET_FIELDS
        assert TOKEN not in response.text

    def test_values_go_to_the_release_namespace_only(self, client, k8s_client, audited, post_json_admin_header, project):
        client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN, "USER": "admin"}}),
            headers=post_json_admin_header
        )
        create = k8s_client["create_namespaced_secret_mock"]
        create.assert_called_once()
        assert create.call_args.args[0] == DEFAULT_NAMESPACE
        body = create.call_args.kwargs["body"]
        assert body.metadata["name"] == "fn-secret-gitea-token"
        assert body.data == {"TOKEN": encoded(TOKEN), "USER": encoded("admin")}

    def test_duplicate_name_conflicts(self, client, k8s_client, audited, post_json_admin_header, secret, project):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": secret.label, "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 409
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_a_secret_belongs_to_no_project(self, client, k8s_client, audited, post_json_admin_header):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json
        assert "project_id" not in response.json

    def test_only_an_admin_creates(
        self, client, k8s_client, audited, post_json_user_header, mock_kc_client
    ):
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.side_effect = (
            lambda token, scope, *args, **kwargs: scope != 'can_do_admin'
        )
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_user_header
        )
        assert response.status_code == 403
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    @pytest.mark.parametrize("provider", [None, "", "VAULT"])
    def test_provider_must_be_a_known_store(self, client, k8s_client, audited, post_json_admin_header, project, provider):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": provider, "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_name_must_leave_room_for_the_key_prefix(self, client, k8s_client, audited, post_json_admin_header):
        prefix = "fn-secret-"
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "x" * (254 - len(prefix)), "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "x" * (253 - len(prefix)), "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json

    @pytest.mark.parametrize("name", ["", "Bad_Name", "x-", "a..b", "a.-b", "a-.b", ".a", "a.", 5, "x" * 254])
    def test_invalid_name(self, client, k8s_client, audited, post_json_admin_header, name, project):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": name, "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_a_non_string_label_is_refused_by_the_model(self, project):
        with pytest.raises(InvalidRequest, match="label must be a string"):
            Secret(label=5, provider=SecretProviderType.K8S)

    @pytest.mark.parametrize("values", [
        None, {}, "TOKEN", ["TOKEN"], {"": "x"}, {"bad key": "x"}, {"a/b": "x"}, {"k" * 254: "x"}, {"TOKEN": ""}, {"TOKEN": 5},
    ])
    def test_invalid_values(self, client, k8s_client, audited, post_json_admin_header, values, project):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": values}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()
        assert Secret.query.count() == 0

    def test_cluster_failure_leaves_no_row(self, client, k8s_client, audited, post_json_admin_header, project):
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(500)
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        assert Secret.query.count() == 0

    def test_existing_cluster_secret_is_overwritten(self, client, k8s_client, audited, post_json_admin_header, project):
        """Registering a secret decides its content, so an old one in the cluster gives way."""
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(409)
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        patch = k8s_client["patch_namespaced_secret_mock"]
        patch.assert_called_once()
        assert patch.call_args.kwargs["body"].data == {"TOKEN": encoded(TOKEN)}

    def test_values_are_redacted_in_the_audit_entry(self, client, k8s_client, audited, post_json_admin_header, project):
        client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers=post_json_admin_header
        )
        entry = Audit.query.filter_by(api_function="post_secret").one()
        assert TOKEN not in entry.details
        assert "*****" in entry.details

    def test_requires_auth(self, client, project):
        response = client.post(
            "/secrets",
            data=json.dumps({"provider": "K8S", "label": "gitea-token", "values": {"TOKEN": TOKEN}}),
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401


class TestPatchSecret:
    def test_rotate(self, client, k8s_client, audited, post_json_admin_header, secret):
        response = client.patch(
            f"/secrets/{secret.label}",
            data=json.dumps({"values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json["label"] == "gitea-token"
        body = k8s_client["create_namespaced_secret_mock"].call_args.kwargs["body"]
        assert body.metadata["name"] == secret.key
        assert body.data == {"TOKEN": encoded("rotated")}

    def test_rotation_patches_an_existing_cluster_secret(self, client, k8s_client, audited, post_json_admin_header, secret):
        k8s_client["create_namespaced_secret_mock"].side_effect = cluster_error(409)
        response = client.patch(
            f"/secrets/{secret.label}",
            data=json.dumps({"values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        body = k8s_client["patch_namespaced_secret_mock"].call_args.kwargs["body"]
        assert body.data == {"TOKEN": encoded("rotated")}

    def test_name_cannot_change(self, client, k8s_client, audited, post_json_admin_header, secret):
        client.patch(
            f"/secrets/{secret.label}",
            data=json.dumps({"label": "another", "values": {"TOKEN": "rotated"}}),
            headers=post_json_admin_header
        )
        assert Secret.get_by_id(secret.id).label == "gitea-token"

    @pytest.mark.parametrize("body", [{}, {"values": {}}, {"values": {"TOKEN": ""}}])
    def test_invalid_values(self, client, k8s_client, audited, post_json_admin_header, secret, body):
        response = client.patch(
            f"/secrets/{secret.label}", data=json.dumps(body), headers=post_json_admin_header
        )
        assert response.status_code == 400
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_not_found(self, client, k8s_client, audited, post_json_admin_header, project):
        response = client.patch(
            "/secrets/missing", data=json.dumps({"values": {"TOKEN": TOKEN}}), headers=post_json_admin_header
        )
        assert response.status_code == 404


class TestDeleteSecret:
    def test_delete(self, client, k8s_client, audited, simple_admin_header, secret):
        store_name = secret.key
        response = client.delete(f"/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 204
        assert Secret.query.count() == 0
        k8s_client["delete_namespaced_secret_mock"].assert_called_once_with(store_name, DEFAULT_NAMESPACE)

    def test_refused_while_a_repository_uses_it(self, client, k8s_client, audited, simple_admin_header, repository):
        response = client.delete(f"/secrets/{repository.secret.label}", headers=simple_admin_header)
        assert response.status_code == 409
        assert Secret.query.count() == 1
        k8s_client["delete_namespaced_secret_mock"].assert_not_called()

    def test_a_secret_shared_by_two_repositories_stays_until_both_are_gone(
        self, client, k8s_client, audited, simple_admin_header, repository, project
    ):
        second = TriggerRepository(
            uri="gitea.fn.svc:3000/org/other", provider="gitea", api_uri="http://gitea.fn.svc:3000/api/v1",
            secret_id=repository.secret_id,
        )
        second.add()

        repository.delete()
        assert client.delete("/secrets/gitea-token", headers=simple_admin_header).status_code == 409

        second.delete()
        assert client.delete("/secrets/gitea-token", headers=simple_admin_header).status_code == 204

    def test_not_locked_by_a_project(self, client, k8s_client, audited, simple_admin_header, secret, project, make_task):
        project.locked = True
        make_task(status="RUNNING")
        response = client.delete(f"/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 204

    def test_only_an_admin_deletes(self, client, k8s_client, audited, simple_user_header, secret, mock_kc_client):
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.side_effect = (
            lambda token, scope, *args, **kwargs: scope != 'can_do_admin'
        )
        assert client.delete(f"/secrets/{secret.label}", headers=simple_user_header).status_code == 403
        assert Secret.query.count() == 1

    def test_missing_cluster_secret_is_fine(self, client, k8s_client, audited, simple_admin_header, secret):
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=404)
        response = client.delete(f"/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 204
        assert Secret.query.count() == 0

    def test_cluster_failure_keeps_the_row(self, client, k8s_client, audited, simple_admin_header, secret):
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=500)
        response = client.delete(f"/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 400
        assert Secret.query.count() == 1

    def test_not_found(self, client, k8s_client, audited, simple_admin_header, project):
        assert client.delete("/secrets/missing", headers=simple_admin_header).status_code == 404


class TestRepositoryReference:
    def test_repositories_share_one_secret(self, client, k8s_client, post_json_admin_header, project, other_project, secret):
        for name in ("repo", "other"):
            response = client.post(
                "/trigger_repositories",
                data=json.dumps({
                    "uri": f"http://gitea.fn.svc:3000/org/{name}", "provider": "gitea",
                    "api_uri": "http://gitea.fn.svc:3000/api/v1", "secret_label": secret.label,
                }),
                headers=post_json_admin_header
            )
            assert response.status_code == 201, response.json
            assert response.json["secret"]["id"] == secret.id

    def test_the_database_rejects_a_missing_secret(self, client, k8s_client, project):
        repo = TriggerRepository(
            uri="gitea.fn.svc:3000/org/repo", provider="gitea", api_uri="http://gitea.fn.svc:3000/api/v1",
            secret_id=9999,
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
                "uri": "http://gitea.fn.svc:3000/org/repo", "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "secret_label": secret.label,
            }),
            headers=post_json_admin_header
        )
        assert response.json["secret"]["key"] == "fn-secret-gitea-token"

    def test_the_token_is_read_from_the_cluster_secret(self, client, k8s_client, repository):
        repository.get_token()
        k8s_client["read_namespaced_secret_mock"].assert_called_once_with(
            "fn-secret-gitea-token", DEFAULT_NAMESPACE
        )

    def test_a_repository_needs_an_existing_secret(self, client, k8s_client, simple_admin_header, post_json_admin_header, project):
        response = client.post(
            "/trigger_repositories",
            data=json.dumps({
                "uri": "http://gitea.fn.svc:3000/org/repo", "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "secret_label": "missing",
            }),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "does not exist" in response.json["error"]

    def test_a_repository_can_reference_a_secret(self, client, k8s_client, post_json_admin_header, project, secret):
        response = client.post(
            "/trigger_repositories",
            data=json.dumps({
                "uri": "http://gitea.fn.svc:3000/org/repo", "provider": "gitea",
                "api_uri": "http://gitea.fn.svc:3000/api/v1", "secret_label": secret.label,
            }),
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json
        assert response.json["secret"]["label"] == "gitea-token"
        assert response.json["provider"] == "gitea"
