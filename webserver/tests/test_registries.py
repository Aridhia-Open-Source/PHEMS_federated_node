import base64
import json
from kubernetes.client import ApiException
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
