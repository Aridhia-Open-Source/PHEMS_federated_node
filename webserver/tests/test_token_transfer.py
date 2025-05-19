import copy
import pytest
from datetime import datetime, timedelta
import json
from unittest import mock
from app.models.request import Request
from app.helpers.exceptions import KeycloakError

@pytest.fixture
def kc_user_mock(mocker, user_uuid):
    return mocker.patch(
        'app.datasets_api.Keycloak.get_user_by_email',
        return_value={"id": user_uuid}
    )

@pytest.fixture
def request_model_body(request_base_body, dataset, user_uuid):
    req_model = copy.deepcopy(request_base_body)
    req_model.pop("dataset_id")
    req_model["dataset"] = dataset
    req_model["requested_by"] = user_uuid

    return req_model

class TestTransfers:
    def test_token_transfer_admin(
            self,
            approve_request,
            client,
            kc_user_mock,
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

    def test_token_transfer_admin_dataset_name(
            self,
            approve_request,
            client,
            request_base_body_name,
            post_json_admin_header
    ):
        """
        Test token transfer is accessible by admin users
        """
        response = client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body_name),
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
        assert response.json == {"error": "Dataset 5012 does not exist"}

    def test_token_transfer_admin_dataset_by_name_not_found(
            self,
            client,
            request_base_body_name,
            post_json_admin_header
    ):
        """
        Test token transfer fails on an non-existing dataset
        """
        request_base_body_name["dataset_name"] = "fake_dataset"
        response = client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body_name),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json == {"error": "Dataset fake_dataset does not exist"}

    @mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
    def test_token_transfer_standard_user(
            self,
            kc_valid_mock,
            client,
            kc_user_mock,
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

    def test_transfer_does_nothing_same_request(
            self,
            client,
            post_json_admin_header,
            access_request,
            kc_user_mock,
            approve_request,
            request_model_body,
            request_base_body,
            dataset
        ):
        """
        Tests that a duplicate request is not accepted.
        """
        Request(**request_model_body).add()

        response = client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            data=json.dumps(request_base_body)
        )
        assert response.status_code == 400
        assert response.json["error"] == 'User already belongs to the active project project1'

    def test_transfer_does_not_override_existing(
            self,
            client,
            post_json_admin_header,
            access_request,
            kc_user_mock,
            approve_request,
            request_model_body,
            request_base_body,
            dataset
        ):
        """
        Tests that a duplicate, or a time-overlapping request
        is not accepted.
        """
        Request(**request_model_body).add()
        request_base_body["proj_end"] = (
            datetime.strptime(request_base_body["proj_end"], "%Y-%m-%d") + timedelta(days=20)
        ).strftime("%Y-%m-%d")

        response = client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            data=json.dumps(request_base_body)
        )
        assert response.status_code == 400

    def test_transfer_successful_same_name_ds_different_time(
            self,
            client,
            post_json_admin_header,
            access_request,
            approve_request,
            kc_user_mock,
            request_model_body,
            request_base_body,
            dataset
        ):
        """
        Tests that a duplicate, not time-overlapping request
        is accepted with same ds and project name.
        """
        request_model_body["proj_end"] = datetime.now().date().strftime("%Y-%m-%d")
        Request(**request_model_body).add()
        request_base_body["proj_start"] = (
            datetime.strptime(request_base_body["proj_end"], "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")

        response = client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            data=json.dumps(request_base_body)
        )
        assert response.status_code == 201

    def test_transfer_only_one_ds_per_project(
            self,
            client,
            post_json_admin_header,
            access_request,
            kc_user_mock,
            approve_request,
            request_model_body,
            request_base_body,
            dataset,
            dataset2
        ):
        """
        Tests that only one dataset per active project is allowed.
        """
        Request(**request_model_body).add()
        request_base_body["dataset_id"] = dataset2.id

        response = client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            data=json.dumps(request_base_body)
        )
        assert response.status_code == 400

    def test_transfer_deleted_if_exception_raised(
            self,
            client,
            post_json_admin_header,
            access_request,
            kc_user_mock,
            request_model_body,
            request_base_body,
            dataset,
            dataset2,
            mocker
        ):
        """
        Tests that the entry is deleted when creating the permission
        in case something goes wrong on approve()
        """
        request_base_body["dataset_id"] = dataset2.id

        mocker.patch("app.helpers.keycloak.Keycloak.get_user_by_id",
                     side_effect=KeycloakError("error"))

        response = client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            data=json.dumps(request_base_body)
        )
        assert response.status_code == 500
        assert Request.query.filter(
            Request.title == request_base_body["title"],
            Request.project_name == request_base_body["project_name"],
        ).count() == 0
