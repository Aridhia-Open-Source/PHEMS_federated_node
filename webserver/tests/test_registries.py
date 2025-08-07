import base64
import json
from kubernetes.client import ApiException

from app.helpers.const import TASK_NAMESPACE, DEFAULT_NAMESPACE
from app.helpers.kubernetes import KubernetesClient
from tests.fixtures.azure_cr_fixtures import *


class TestGetRegistriesApi:
    def test_list_200(
        self,
        registry,
        client,
        simple_admin_header
    ):
        """
        Basic test for the GET /registries endpoint
        ensuring the expected response body
        """
        resp = client.get(
            "/registries",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert resp.json["items"] == [{
            'id': registry.id,
            'needs_auth': registry.needs_auth,
            'active': registry.active,
            'url': registry.url
        }]

    def test_list_non_admin_403(
        self,
        registry,
        client,
        simple_user_header,
        reg_k8s_client
    ):
        """
        Basic test for the GET /registries endpoint
        ensuring only admins can get information
        """
        resp = client.get(
            "/registries",
            headers=simple_user_header
        )
        assert resp.status_code == 403

    def test_list_no_auth_401(
        self,
        registry,
        client,
        simple_user_header
    ):
        """
        Basic test for the GET /registries endpoint
        ensuring only admins can get information
        """
        resp = client.get("/registries")
        assert resp.status_code == 401

    def test_get_registry_by_id(
        self,
        registry,
        client,
        simple_admin_header
    ):
        """
        Basic test to check that the registry
        output is correct with appropriate permissions
        """
        resp = client.get(
            f"registries/{registry.id}",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert resp.json == {
            "id": registry.id,
            "needs_auth": registry.needs_auth,
            'active': registry.active,
            "url": registry.url
        }


    def test_get_registry_by_id_not_found(
        self,
        registry,
        client,
        simple_admin_header
    ):
        """
        Basic test that a 404 is return with an
        appropriate message
        """
        resp = client.get(
            f"registries/{registry.id + 1}",
            headers=simple_admin_header
        )
        assert resp.status_code == 404
        assert resp.json["error"] == "Registry not found"

    def test_get_registry_by_id_non_admin_403(
        self,
        registry,
        client,
        simple_user_header
    ):
        """
        Basic test to ensure only admins can browse
        by registry id
        """
        resp = client.get(
            f"registries/{registry.id}",
            headers=simple_user_header
        )
        assert resp.status_code == 403


class TestPostRegistriesApi:
    def test_create_registry_201(
        self,
        client,
        post_json_admin_header,
        reg_k8s_client
    ):
        """
        Basic POST request
        """
        new_registry = "shiny.azurecr.io"

        with responses.RequestsMock() as rsps:
            rsps.add_passthru(KEYCLOAK_URL)
            rsps.add(
                responses.GET,
                f"https://{new_registry}/oauth2/token?service={new_registry}&scope=registry:catalog:*",
                json={"access_token": "12jio12buds89"},
                status=200
            )
            resp = client.post(
                "/registries",
                json={
                    "url": new_registry,
                    "username": "blabla",
                    "password": "secret"
                },
                headers=post_json_admin_header
            )
        assert resp.status_code == 201

    def test_create_registry_201_missing_taskpull_secret(
        self,
        client,
        post_json_admin_header,
        reg_k8s_client
    ):
        """
        Basic POST request for the first time. K8s will return a 404
        so it should create a brand new
        """
        new_registry = "shiny.azurecr.io"

        reg_k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(
            http_resp=Mock(status=404, body="details", reason="Failed")
        )
        with responses.RequestsMock() as rsps:
            rsps.add_passthru(KEYCLOAK_URL)
            rsps.add(
                responses.GET,
                f"https://{new_registry}/oauth2/token?service={new_registry}&scope=registry:catalog:*",
                json={"access_token": "12jio12buds89"},
                status=200
            )
            resp = client.post(
                "/registries",
                json={
                    "url": new_registry,
                    "username": "blabla",
                    "password": "secret"
                },
                headers=post_json_admin_header
            )
        assert resp.status_code == 201
        reg_k8s_client["create_namespaced_secret_mock"].assert_called()

    def test_create_registry_incorrect_creds(
        self,
        client,
        post_json_admin_header
    ):
        """
        Basic POST request with incorrect credentials
        """
        new_registry = "shiny.azurecr.io"
        with responses.RequestsMock() as rsps:
            rsps.add_passthru(KEYCLOAK_URL)
            rsps.add(
                responses.GET,
                f"https://{new_registry}/oauth2/token?service={new_registry}&scope=registry:catalog:*",
                json={"error": "Invalid credentials"},
                status=401
            )
            resp = client.post(
                "/registries",
                json={
                    "url": new_registry,
                    "username": "blabla",
                    "password": "secret"
                },
                headers=post_json_admin_header
            )
        assert resp.status_code == 400
        assert resp.json["error"] == "Could not authenticate against the registry"

    def test_create_missing_field(
        self,
        client,
        post_json_admin_header
    ):
        """
        Checks that required fields missing return
        an error message
        """
        resp = client.post(
            "/registries",
            json={
                "username": "blabla",
                "password": "secret"
            },
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json["error"] == 'Field "url" missing'

    def test_create_duplicate(
        self,
        client,
        registry,
        post_json_admin_header
    ):
        """
        Checks that creating a registry with the same
        url as an existing one, fails
        """
        with responses.RequestsMock() as rsps:
            rsps.add_passthru(KEYCLOAK_URL)
            rsps.add(
                responses.GET,
                f"https://{registry.url}/oauth2/token?service={registry.url}&scope=registry:catalog:*",
                json={"access_token": "12jio12buds89"},
                status=200
            )
            resp = client.post(
                "/registries",
                json={
                    "url": registry.url,
                    "username": "blabla",
                    "password": "secret"
                },
                headers=post_json_admin_header
            )
        assert resp.status_code == 400
        assert resp.json["error"] == f"Registry {registry.url} already exist"
        assert Registry.query.filter_by(url=registry.url).count() == 1

class TestDeleteRegistries:
    def test_delete_registry(
            self,
            client,
            registry,
            reg_k8s_client,
            simple_admin_header
    ):
        """
        Simple test to check a successful deletion from the
        DB and its k8s secrets
        """
        expected_taskspull = KubernetesClient.encode_secret_value(json.dumps({"auths": {}}))
        secret_name = registry.slugify_name()
        response = client.delete(
            f"/registries/{registry.id}",
            headers=simple_admin_header
        )
        assert response.status_code == 204
        patch_delete = reg_k8s_client["patch_namespaced_secret_mock"].mock_calls[1]
        assert patch_delete[-1]["name"] == "taskspull"
        assert patch_delete[-1]["namespace"] == TASK_NAMESPACE
        assert patch_delete[-1]["body"].data[".dockerconfigjson"] == expected_taskspull
        reg_k8s_client["delete_namespaced_secret_mock"].assert_called_with(
            **{"name": secret_name, "namespace": DEFAULT_NAMESPACE}
        )

    def test_delete_registry_not_found(
            self,
            client,
            registry,
            reg_k8s_client,
            simple_admin_header
    ):
        """
        Return a 404 response if a registry cannot be found
        """
        response = client.delete(
            f"/registries/{registry.id + 1}",
            headers=simple_admin_header
        )
        assert response.status_code == 404

    def test_delete_registry_k8s_error(
            self,
            client,
            registry,
            reg_k8s_client,
            simple_admin_header
    ):
        """
        Return a 500 stauts code when a k8s exception is raised
            but the db record is still deleted. This is an intentional
            behaviour as the sync and container check are based
            on the db entry. Secrets can stay if k8s fails.
        """
        reg_k8s_client["patch_namespaced_secret_mock"].side_effect = ApiException(
            http_resp=Mock(status=500, reason="Error", data="Invalid value in data")
        )
        reg_id = registry.id
        response = client.delete(
            f"/registries/{reg_id}",
            headers=simple_admin_header
        )
        assert response.status_code == 500
        assert Registry.query.filter_by(id=reg_id).one_or_none() is None

    def test_delete_cascade_containers(
            self,
            client,
            registry,
            reg_k8s_client,
            simple_admin_header
    ):
        """
        Tests that by simply deleting a registry all of its
        containers are deleted as well
        """
        reg_id = registry.id
        Container(
            registry=registry,
            name="newimage",
            tag="1.0.0"
        ).add()
        Container(
            registry=registry,
            name="newimage",
            tag="1.3.0"
        ).add()

        response = client.delete(
            f"/registries/{reg_id}",
            headers=simple_admin_header
        )
        assert response.status_code == 204
        assert Registry.query.filter_by(id=reg_id).one_or_none() is None
        assert Container.query.filter_by(
            name="newimage", registry_id=reg_id
            ).count() == 0

class TestPatchRegistriesApi:
    def test_patch_registry(
        self,
        client,
        registry,
        post_json_admin_header,
        k8s_client
    ):
        """
        Simple PATCH request test to check the db record is updated
        """
        data = {
            "active": not registry.active
        }
        resp = client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 204
        assert registry.active == data["active"]
        # it patches the regcreds-like secret at registry creation
        k8s_client["patch_namespaced_secret_mock"].call_count == 1

    def test_patch_registry_credentials(
        self,
        client,
        registry,
        post_json_admin_header,
        k8s_client
    ):
        """
        Simple PATCH request test to check the registry credentials
        are updated
        """
        data = {
            "password": "new password token",
            "username": "shiny"
        }
        encoded_pass = base64.b64encode("new password token".encode()).decode()
        encoded_user = base64.b64encode("shiny".encode()).decode()
        resp = client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 204
        k8s_client["patch_namespaced_secret_mock"].assert_called()

        # Only look after the first invocation as the first comes from the registry creation
        taskspull_secret = k8s_client["patch_namespaced_secret_mock"].call_args_list[1][1]
        reg_secret = k8s_client["patch_namespaced_secret_mock"].call_args_list[2][1]

        assert taskspull_secret["name"] == "taskspull"
        dockerconfig = base64.b64decode(taskspull_secret['body'].data['.dockerconfigjson']).decode()
        assert json.loads(dockerconfig)["auths"][registry.url]["password"] == data["password"]
        assert json.loads(dockerconfig)["auths"][registry.url]["username"] == data["username"]
        assert reg_secret["name"] == "acr-azurecr-io"
        assert reg_secret["body"].data["TOKEN"] == encoded_pass
        assert reg_secret["body"].data["USER"] == encoded_user

    def test_patch_registry_empty_body(
        self,
        client,
        registry,
        post_json_admin_header,
        k8s_client
    ):
        """
        Simple PATCH request test to check the registry credentials
        are updated
        """
        data = {}
        resp = client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 204
        # it patches the regcreds-like secret at registry creation
        k8s_client["patch_namespaced_secret_mock"].call_count == 1

    def test_patch_registry_non_existent(
        self,
        client,
        registry,
        post_json_admin_header
    ):
        """
        Simple PATCH request test to ensure that trying to patch
        an non existing registry returns an error
        """
        data = {
            "active": not registry.active
        }
        resp = client.patch(
            f"registries/{registry.id + 1}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json["error"] == f"Registry {registry.id + 1} not found"

    def test_patch_registry_url_change_not_allowed(
        self,
        client,
        registry,
        post_json_admin_header
    ):
        """
        Simple PATCH request test to ensure that trying to change a url
        is not allowed. New url should be a new registry
        """
        data = {
            "host": "fancy.acr.io"
        }
        resp = client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json["error"] == "Field host is not valid"

    def test_patch_registry_k8s_fail(
        self,
        client,
        registry,
        post_json_admin_header,
        k8s_client
    ):
        """
        Simple PATCH request test to check the db record is updated
        """
        data = {
            "password": "pass"
        }
        k8s_client["patch_namespaced_secret_mock"].side_effect = ApiException(
            http_resp=Mock(status=500, body="details", reason="Failed")
        )

        resp = client.patch(
            f"registries/{registry.id}",
            json=data,
            headers=post_json_admin_header
        )
        assert resp.status_code == 400
        assert resp.json["error"] == "Could not update credentials"
