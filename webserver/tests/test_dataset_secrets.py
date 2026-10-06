"""
A dataset's credentials live in a k8s secret it references by name. Creating, updating and
deleting a dataset never touches Kubernetes; only reading the credentials does.
"""
import json

import pytest

from app.helpers.const import DEFAULT_NAMESPACE
from app.models.dataset import Dataset
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType


@pytest.fixture
def audited(mock_kc_client, admin_user_uuid):
    """POST, PATCH and DELETE are audited, which looks the caller up in Keycloak."""
    mock_kc_client["wrappers_kc"].return_value.get_user_by_email.return_value["id"] = admin_user_uuid


@pytest.fixture
def secret(client, k8s_client, project):
    secret = Secret(project_id=project.id, label="cdm-creds", provider=SecretProviderType.K8S)
    secret.add()
    return secret


@pytest.fixture
def body(project, secret):
    return {
        "name": "cdm",
        "host": "db.example.com",
        "secret_label": secret.label,
        "read_schema": "cdm",
        "write_schema": "results",
        "project_id": project.id,
    }


def post_dataset(client, headers, body, code=201):
    response = client.post("/datasets", data=json.dumps(body), headers=headers)
    assert response.status_code == code, response.text
    return response.json


def assert_kubernetes_untouched(k8s_client):
    for name in ("create_namespaced_secret_mock", "patch_namespaced_secret_mock", "delete_namespaced_secret_mock"):
        k8s_client[name].assert_not_called()


class TestPostDataset:
    def test_create(self, client, k8s_client, audited, post_json_admin_header, body):
        created = post_dataset(client, post_json_admin_header, body)
        assert created["secret"]["label"] == "cdm-creds"
        assert created["read_schema"] == "cdm"
        assert Dataset.query.filter_by(name="cdm").one().secret.label == "cdm-creds"

    def test_never_touches_kubernetes(self, client, k8s_client, audited, post_json_admin_header, body):
        post_dataset(client, post_json_admin_header, body)
        assert_kubernetes_untouched(k8s_client)

    def test_response_has_no_credentials(self, client, k8s_client, audited, post_json_admin_header, body):
        created = post_dataset(client, post_json_admin_header, body)
        assert "username" not in created
        assert "password" not in created

    def test_secret_must_exist(self, client, k8s_client, audited, post_json_admin_header, body):
        body["secret_label"] = "missing"
        response = post_dataset(client, post_json_admin_header, body, code=400)
        assert "does not exist" in response["error"]
        assert Dataset.query.count() == 0

    def test_secret_is_required(self, client, k8s_client, audited, post_json_admin_header, body):
        del body["secret_label"]
        post_dataset(client, post_json_admin_header, body, code=400)
        assert Dataset.query.count() == 0

    def test_another_projects_secret_is_rejected(
        self, client, k8s_client, audited, post_json_admin_header, body, other_project
    ):
        Secret(project_id=other_project.id, label="foreign-creds", provider=SecretProviderType.K8S).add()
        body["secret_label"] = "foreign-creds"
        response = post_dataset(client, post_json_admin_header, body, code=400)
        assert "does not exist" in response["error"]
        assert Dataset.query.count() == 0

    def test_the_response_names_the_cluster_secret(self, client, k8s_client, audited, post_json_admin_header, body, project):
        created = post_dataset(client, post_json_admin_header, body)
        assert created["secret"]["key"] == f"{project.id}-cdm-creds"

    @pytest.mark.parametrize("credentials", [{"username": "u"}, {"password": "p"}, {"username": "u", "password": "p"}])
    def test_credentials_are_rejected(self, client, k8s_client, audited, post_json_admin_header, body, credentials):
        response = post_dataset(client, post_json_admin_header, {**body, **credentials}, code=400)
        assert "secret_label" in response["error"]
        assert Dataset.query.count() == 0

    def test_datasets_can_share_a_secret(self, client, k8s_client, audited, post_json_admin_header, body):
        post_dataset(client, post_json_admin_header, body)
        post_dataset(client, post_json_admin_header, {**body, "name": "other"})
        assert Dataset.query.filter_by(secret_id=Dataset.query.first().secret_id).count() == 2


class TestPatchDataset:
    def create(self, client, headers, body):
        return post_dataset(client, headers, body)

    def test_repoint_to_another_secret(self, client, k8s_client, audited, post_json_admin_header, body, project):
        created = self.create(client, post_json_admin_header, body)
        Secret(project_id=project.id, label="other-creds", provider=SecretProviderType.K8S).add()

        response = client.patch(
            f"/datasets/{created['id']}",
            data=json.dumps({"secret_label": "other-creds"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 202, response.text
        assert response.json["secret"]["label"] == "other-creds"
        assert_kubernetes_untouched(k8s_client)

    def test_rename_does_not_touch_the_secret(self, client, k8s_client, audited, post_json_admin_header, body):
        """The secret's name used to be derived from the dataset's, so a rename had to move it."""
        created = self.create(client, post_json_admin_header, body)
        response = client.patch(
            f"/datasets/{created['id']}", data=json.dumps({"name": "renamed"}), headers=post_json_admin_header
        )
        assert response.status_code == 202, response.text
        assert response.json["secret"]["label"] == "cdm-creds"
        assert_kubernetes_untouched(k8s_client)

    def test_new_secret_must_exist(self, client, k8s_client, audited, post_json_admin_header, body):
        created = self.create(client, post_json_admin_header, body)
        response = client.patch(
            f"/datasets/{created['id']}",
            data=json.dumps({"secret_label": "missing"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert Dataset.query.one().secret.label == "cdm-creds"

    def test_another_projects_secret_is_rejected(
        self, client, k8s_client, audited, post_json_admin_header, body, other_project
    ):
        created = self.create(client, post_json_admin_header, body)
        Secret(project_id=other_project.id, label="foreign-creds", provider=SecretProviderType.K8S).add()
        response = client.patch(
            f"/datasets/{created['id']}",
            data=json.dumps({"secret_label": "foreign-creds"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "does not exist" in response.json["error"]
        assert Dataset.query.one().secret.label == "cdm-creds"

    @pytest.mark.parametrize("field", ["username", "password"])
    def test_credentials_are_not_a_field(self, client, k8s_client, audited, post_json_admin_header, body, field):
        created = self.create(client, post_json_admin_header, body)
        response = client.patch(
            f"/datasets/{created['id']}", data=json.dumps({field: "x"}), headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "not a valid one" in response.json["error"]


class TestDeleteDataset:
    def test_delete_leaves_the_secret_alone(self, client, k8s_client, audited, post_json_admin_header, simple_admin_header, body):
        created = post_dataset(client, post_json_admin_header, body)
        response = client.delete(f"/datasets/{created['id']}", headers=simple_admin_header)
        assert response.status_code == 204
        assert Dataset.query.count() == 0
        assert Secret.query.filter_by(label="cdm-creds").count() == 1
        assert_kubernetes_untouched(k8s_client)

    def test_secret_cannot_be_deleted_while_a_dataset_uses_it(
        self, client, k8s_client, audited, post_json_admin_header, simple_admin_header, body, secret
    ):
        post_dataset(client, post_json_admin_header, body)
        response = client.delete(f"/projects/{secret.project_id}/secrets/{secret.label}", headers=simple_admin_header)
        assert response.status_code == 409
        k8s_client["delete_namespaced_secret_mock"].assert_not_called()

    def test_secret_can_be_deleted_once_no_dataset_uses_it(
        self, client, k8s_client, audited, post_json_admin_header, simple_admin_header, body, secret
    ):
        created = post_dataset(client, post_json_admin_header, body)
        client.delete(f"/datasets/{created['id']}", headers=simple_admin_header)
        assert client.delete(f"/projects/{secret.project_id}/secrets/{secret.label}", headers=simple_admin_header).status_code == 204


class TestGetCredentials:
    def test_reads_the_named_secret(self, client, k8s_client, audited, post_json_admin_header, body, project):
        created = post_dataset(client, post_json_admin_header, body)
        dataset = Dataset.get_by_id(created["id"])

        user, password = dataset.get_credentials()

        read = k8s_client["read_namespaced_secret_mock"]
        read.assert_called_once_with(f"{project.id}-cdm-creds", DEFAULT_NAMESPACE)
        assert (user, password) == ("abc123", "abc123")

    def test_two_datasets_sharing_a_secret_read_the_same_one(self, client, k8s_client, audited, post_json_admin_header, body, project):
        first = Dataset.get_by_id(post_dataset(client, post_json_admin_header, body)["id"])
        second = Dataset.get_by_id(post_dataset(client, post_json_admin_header, {**body, "name": "other"})["id"])

        first.get_credentials()
        second.get_credentials()

        names = {call.args[0] for call in k8s_client["read_namespaced_secret_mock"].call_args_list}
        assert names == {f"{project.id}-cdm-creds"}
