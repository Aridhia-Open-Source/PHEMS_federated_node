"""
A dataset's credentials live in a k8s secret it references by name. Creating, updating and
deleting a dataset never touches Kubernetes; only reading the credentials does.
"""
import json

import pytest

from app.helpers.const import DEFAULT_NAMESPACE
from app.models.dataset import Dataset
from app.models.k8s_secret import K8sSecret


@pytest.fixture
def audited(mock_kc_client, admin_user_uuid):
    """POST, PATCH and DELETE are audited, which looks the caller up in Keycloak."""
    mock_kc_client["wrappers_kc"].return_value.get_user_by_email.return_value["id"] = admin_user_uuid


@pytest.fixture
def k8s_secret(client, k8s_client):
    secret = K8sSecret(name="cdm-creds")
    secret.add()
    return secret


@pytest.fixture
def body(project, k8s_secret):
    return {
        "name": "cdm",
        "host": "db.example.com",
        "k8s_secret_name": k8s_secret.name,
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
        assert created["k8s_secret_name"] == "cdm-creds"
        assert created["read_schema"] == "cdm"
        assert Dataset.query.filter_by(name="cdm").one().k8s_secret_name == "cdm-creds"

    def test_never_touches_kubernetes(self, client, k8s_client, audited, post_json_admin_header, body):
        post_dataset(client, post_json_admin_header, body)
        assert_kubernetes_untouched(k8s_client)

    def test_response_has_no_credentials(self, client, k8s_client, audited, post_json_admin_header, body):
        created = post_dataset(client, post_json_admin_header, body)
        assert "username" not in created
        assert "password" not in created

    def test_secret_must_exist(self, client, k8s_client, audited, post_json_admin_header, body):
        body["k8s_secret_name"] = "missing"
        response = post_dataset(client, post_json_admin_header, body, code=400)
        assert "does not exist" in response["error"]
        assert Dataset.query.count() == 0

    def test_secret_is_required(self, client, k8s_client, audited, post_json_admin_header, body):
        del body["k8s_secret_name"]
        post_dataset(client, post_json_admin_header, body, code=400)
        assert Dataset.query.count() == 0

    @pytest.mark.parametrize("credentials", [{"username": "u"}, {"password": "p"}, {"username": "u", "password": "p"}])
    def test_credentials_are_rejected(self, client, k8s_client, audited, post_json_admin_header, body, credentials):
        response = post_dataset(client, post_json_admin_header, {**body, **credentials}, code=400)
        assert "k8s_secret_name" in response["error"]
        assert Dataset.query.count() == 0

    def test_datasets_can_share_a_secret(self, client, k8s_client, audited, post_json_admin_header, body):
        post_dataset(client, post_json_admin_header, body)
        post_dataset(client, post_json_admin_header, {**body, "name": "other"})
        assert Dataset.query.filter_by(k8s_secret_name="cdm-creds").count() == 2


class TestPatchDataset:
    def create(self, client, headers, body):
        return post_dataset(client, headers, body)

    def test_repoint_to_another_secret(self, client, k8s_client, audited, post_json_admin_header, body):
        created = self.create(client, post_json_admin_header, body)
        K8sSecret(name="other-creds").add()

        response = client.patch(
            f"/datasets/{created['id']}",
            data=json.dumps({"k8s_secret_name": "other-creds"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 202, response.text
        assert response.json["k8s_secret_name"] == "other-creds"
        assert_kubernetes_untouched(k8s_client)

    def test_rename_does_not_touch_the_secret(self, client, k8s_client, audited, post_json_admin_header, body):
        """The secret's name used to be derived from the dataset's, so a rename had to move it."""
        created = self.create(client, post_json_admin_header, body)
        response = client.patch(
            f"/datasets/{created['id']}", data=json.dumps({"name": "renamed"}), headers=post_json_admin_header
        )
        assert response.status_code == 202, response.text
        assert response.json["k8s_secret_name"] == "cdm-creds"
        assert_kubernetes_untouched(k8s_client)

    def test_new_secret_must_exist(self, client, k8s_client, audited, post_json_admin_header, body):
        created = self.create(client, post_json_admin_header, body)
        response = client.patch(
            f"/datasets/{created['id']}",
            data=json.dumps({"k8s_secret_name": "missing"}),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert Dataset.query.one().k8s_secret_name == "cdm-creds"

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
        assert K8sSecret.query.filter_by(name="cdm-creds").count() == 1
        assert_kubernetes_untouched(k8s_client)

    def test_secret_cannot_be_deleted_while_a_dataset_uses_it(
        self, client, k8s_client, audited, post_json_admin_header, simple_admin_header, body, k8s_secret
    ):
        post_dataset(client, post_json_admin_header, body)
        response = client.delete(f"/k8s_secrets/{k8s_secret.id}", headers=simple_admin_header)
        assert response.status_code == 409
        k8s_client["delete_namespaced_secret_mock"].assert_not_called()

    def test_secret_can_be_deleted_once_no_dataset_uses_it(
        self, client, k8s_client, audited, post_json_admin_header, simple_admin_header, body, k8s_secret
    ):
        created = post_dataset(client, post_json_admin_header, body)
        client.delete(f"/datasets/{created['id']}", headers=simple_admin_header)
        assert client.delete(f"/k8s_secrets/{k8s_secret.id}", headers=simple_admin_header).status_code == 204


class TestGetCredentials:
    def test_reads_the_named_secret(self, client, k8s_client, audited, post_json_admin_header, body):
        created = post_dataset(client, post_json_admin_header, body)
        dataset = Dataset.get_by_id(created["id"])

        user, password = dataset.get_credentials()

        read = k8s_client["read_namespaced_secret_mock"]
        read.assert_called_once_with("cdm-creds", DEFAULT_NAMESPACE)
        assert (user, password) == ("abc123", "abc123")

    def test_two_datasets_sharing_a_secret_read_the_same_one(self, client, k8s_client, audited, post_json_admin_header, body):
        first = Dataset.get_by_id(post_dataset(client, post_json_admin_header, body)["id"])
        second = Dataset.get_by_id(post_dataset(client, post_json_admin_header, {**body, "name": "other"})["id"])

        first.get_credentials()
        second.get_credentials()

        names = {call.args[0] for call in k8s_client["read_namespaced_secret_mock"].call_args_list}
        assert names == {"cdm-creds"}
