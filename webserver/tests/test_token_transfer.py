import json
import pytest
from datetime import datetime as dt, timedelta

@pytest.fixture
def request_base_body(dataset):
    return {
        "title": "Test Task",
        "dataset_id": dataset.id,
        "project_name": "project1",
        "requested_by": { "email": "test@test.com" },
        "description": "First task ever!",
        "proj_start": dt.now().date().strftime("%Y-%m-%d"),
        "proj_end": (dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    }

class TestTransfers:
    def test_token_transfer_admin(
            self,
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

    def test_token_transfer_standard_user(
            self,
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
        assert response.status_code == 401

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
        assert response.status_code == 401
