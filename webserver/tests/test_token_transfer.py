import json
from unittest import mock


class TestTransfers:
    def test_token_transfer_admin(
            self,
            approve_request,
            client,
            request_base_body,
            post_json_admin_header
    ):
        """
        Test token transfer is accessible by admin users
        """
        response = client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert list(response.json.keys()) == ["token"]

    def test_token_transfer_admin_missing_requester_email_fails(
            self,
            client,
            request_base_body,
            post_json_admin_header
    ):
        """
        Test token transfer fails if the requester's email is not provided
        """
        request_base_body["requested_by"].pop("email")
        response = client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_token_transfer_admin_dataset_not_found(
            self,
            client,
            request_base_body,
            post_json_admin_header
    ):
        """
        Test token transfer fails on an non-existing dataset
        """
        request_base_body["dataset_id"] = 5012
        response = client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json == {"error": "Dataset 5012 not found"}

    @mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
    def test_token_transfer_standard_user(
            self,
            kc_valid_mock,
            client,
            request_base_body,
            post_json_user_header
    ):
        """
        Test token transfer is accessible by admin users
        """
        response = client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body),
            headers=post_json_user_header
        )
        assert response.status_code == 403

    def test_workspace_token_transfer_admin(
            self,
            client,
            simple_admin_header
    ):
        """
        Test token transfer is not accessible by non-admin users
        """
        response = client.post(
            "/datasets/workspace/token",
            headers=simple_admin_header
        )
        assert response.status_code == 200

    def test_workspace_token_transfer_standard_user(
            self,
            client,
            simple_user_header
    ):
        """
        Test workspace token transfer is not accessible by non-admin users
        """
        response = client.post(
            "/datasets/workspace/token",
            headers=simple_user_header
        )
        assert response.status_code == 403
