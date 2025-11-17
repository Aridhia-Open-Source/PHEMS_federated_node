from unittest.mock import Mock
from kubernetes.client.exceptions import ApiException


class TestUpdateDeliverySecret:
    def test_other_delivery_secret(
        self,
        client,
        set_task_other_delivery_env,
        post_json_admin_header,
        k8s_client
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, the secret is correctly
        updated
        """
        resp = client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 204
        secret_body = k8s_client["list_namespaced_secret_mock"].return_value.items[0]
        k8s_client["patch_namespaced_secret_mock"].assert_called_with(
            'url.delivery.com', "fn-controller", secret_body
        )
        # Check that the provided secret is base64 encoded
        assert k8s_client["patch_namespaced_secret_mock"].call_args[0][-1].data["auth"] == "dGVzdA=="

    def test_other_delivery_secret_403_non_admin(
        self,
        client,
        set_task_other_delivery_env,
        post_json_user_header,
        k8s_client
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, 403 is returned for non-admins
        """
        resp = client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_user_header
        )

        assert resp.status_code == 403
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()

    def test_other_delivery_secret_missing_mandatory_field(
        self,
        client,
        set_task_other_delivery_env,
        post_json_admin_header,
        k8s_client
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, an error is returned if
        the mandatory "auth" field is missing
        """
        resp = client.patch(
            "/delivery-secret",
            json={"new": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json["error"] == "auth field is mandatory"
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()

    def test_other_delivery_secret_body_not_json(
        self,
        client,
        set_task_other_delivery_env,
        post_form_admin_header,
        k8s_client
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, an error is returned if
        the request body is not json
        """
        resp = client.patch(
            "/delivery-secret",
            data="{\"auth\": \"test\"}",
            headers=post_form_admin_header
        )

        assert resp.status_code == 400
        assert resp.json["error"] == "Set a json body"
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()

    def test_other_delivery_secret_not_found(
        self,
        client,
        set_task_other_delivery_env,
        post_json_admin_header,
        k8s_client
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, if the secret is not found
        nothing is updated
        """
        k8s_client["list_namespaced_secret_mock"].return_value.items = []
        resp = client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()

    def test_other_delivery_secret_error_patching(
        self,
        client,
        set_task_other_delivery_env,
        post_json_admin_header,
        k8s_client
    ):
        """
        Test that when the other delivery is chosen
        at deployment time, if the secret patching fails
        the repsonse is handled appropriately
        """
        k8s_client["patch_namespaced_secret_mock"].side_effect = ApiException(
            http_resp=Mock(status=500, reason="Error", data="Something went wrong")
        )
        resp = client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 500
        assert resp.json["error"] == "Could not update the secret. Check the logs for more details"

    def test_github_delivery_secret(
        self,
        client,
        set_task_github_delivery_env,
        post_json_admin_header,
        k8s_client
    ):
        """
        Test that when the github delivery is chosen
        at deployment time, an error is always returned
        """
        resp = client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json["error"] == "Unable to update GitHub delivery details for security reasons. Please contact the system administrator"
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()

    def test_delivery_secret_feature_non_available(
        self,
        client,
        post_json_admin_header,
        k8s_client
    ):
        """
        Test that when the task controller is not deployed
        the feature not available error is returned
        """
        resp = client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json["error"] == "The Task Controller feature is not available on this Federated Node"
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()
