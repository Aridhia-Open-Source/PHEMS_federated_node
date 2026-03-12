from pytest import mark
from pytest_asyncio import fixture

from unittest.mock import Mock
from kubernetes_asyncio.client.exceptions import ApiException


class TestUpdateDeliverySecret:
    @fixture
    def v1_delivery_mock(self, mocker, mock_args_k8s, delivery_secret_mock):
        mock_args_k8s.api_client.read_namespaced_secret.return_value = delivery_secret_mock
        mock_args_k8s.api_client.list_namespaced_secret.return_value.items = [delivery_secret_mock]
        return mocker.patch(
            'app.routes.admin.KubernetesClient.create',
            name="v1_routes_admin",
            return_value=mock_args_k8s
        )

    @mark.asyncio
    async def test_other_delivery_secret(
        self,
        client,
        set_task_other_delivery_env,
        post_json_admin_header,
        mock_args_k8s,
        v1_delivery_mock
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, the secret is correctly
        updated
        """
        resp = await client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 204
        secret_body = mock_args_k8s.api_client.list_namespaced_secret.return_value.items[0]
        mock_args_k8s.api_client.patch_namespaced_secret.assert_called_with(
            'url.delivery.com', "fn-controller", secret_body
        )
        # Check that the provided secret is base64 encoded
        mock_args_k8s.api_client.patch_namespaced_secret.call_args[0][-1].data["auth"] == "dGVzdA=="

    @mark.asyncio
    async def test_other_delivery_secret_403_non_admin(
        self,
        client,
        set_task_other_delivery_env,
        post_json_user_header,
        mock_kc_client,
        mock_args_k8s,
        v1_delivery_mock
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, 403 is returned for non-admins
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        resp = await client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_user_header
        )

        assert resp.status_code == 403
        mock_args_k8s.api_client.patch_namespaced_secret.assert_not_called()

    @mark.asyncio
    async def test_other_delivery_secret_missing_mandatory_field(
        self,
        client,
        set_task_other_delivery_env,
        post_json_admin_header,
        mock_args_k8s,
        v1_delivery_mock
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, an error is returned if
        the mandatory "auth" field is missing
        """
        resp = await client.patch(
            "/delivery-secret",
            json={"new": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json()["error"][0]["message"] == "Field required"
        assert "auth" in resp.json()["error"][0]["field"]
        mock_args_k8s.api_client.patch_namespaced_secret.assert_not_called()

    @mark.asyncio
    async def test_other_delivery_secret_body_not_json(
        self,
        client,
        set_task_other_delivery_env,
        post_form_admin_header,
        mock_args_k8s,
        v1_delivery_mock
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, an error is returned if
        the request body is not json
        """
        resp = await client.patch(
            "/delivery-secret",
            data="{\"auth\": \"test\"}",
            headers=post_form_admin_header
        )

        assert resp.status_code == 400
        assert 'Input should be a valid dictionary or object to extract fields from' == resp.json()["error"][0]["message"]
        mock_args_k8s.api_client.patch_namespaced_secret.assert_not_called()

    @mark.asyncio
    async def test_other_delivery_secret_not_found(
        self,
        client,
        set_task_other_delivery_env,
        post_json_admin_header,
        mock_args_k8s,
        v1_delivery_mock
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, if the secret is not found
        nothing is updated
        """
        mock_args_k8s.api_client.list_namespaced_secret.return_value.items = []
        resp = await client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        mock_args_k8s.api_client.patch_namespaced_secret.assert_not_called()

    @mark.asyncio
    async def test_other_delivery_secret_error_patching(
        self,
        client,
        set_task_other_delivery_env,
        post_json_admin_header,
        mock_args_k8s,
        v1_delivery_mock
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, if the secret patching fails
        the repsonse is handled appropriately
        """
        mock_args_k8s.api_client.patch_namespaced_secret.side_effect = ApiException(
            http_resp=Mock(status=500, reason="Error", data="Something went wrong")
        )
        resp = await client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 500
        assert resp.json()["error"] == "Could not update the secret. Check the logs for more details"

    @mark.asyncio
    async def test_github_delivery_secret(
        self,
        client,
        set_task_github_delivery_env,
        post_json_admin_header,
        mock_args_k8s,
        v1_delivery_mock
    ):
        """
        Test that when the github delivery is chosen
        at deployment time, an error is always returned
        """
        resp = await client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json()["error"] == "Unable to update GitHub delivery details for security reasons. Please contact the system administrator"
        mock_args_k8s.api_client.patch_namespaced_secret.assert_not_called()

    @mark.asyncio
    async def test_delivery_secret_feature_non_available(
        self,
        client,
        post_json_admin_header,
        mock_args_k8s,
        v1_delivery_mock
    ):
        """
        Test that when the task controller is not deployed
        the feature not available error is returned
        """
        resp = await client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json()["error"] == "The Task Controller feature is not available on this Federated Node"
        mock_args_k8s.api_client.patch_namespaced_secret.assert_not_called()
