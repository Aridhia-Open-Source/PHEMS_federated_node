import copy
from pytest_asyncio import fixture
from pytest import mark
from datetime import datetime, timedelta

from sqlalchemy import func, select
from app.models.request import RequestModel
from app.helpers.exceptions import KeycloakError
from tests.base_test_class import BaseTest


@fixture
def request_model_body(request_object_init, dataset, user_uuid):
    req_model = copy.deepcopy(request_object_init)
    req_model.pop("dataset_id")
    req_model["dataset"] = dataset
    req_model["requested_by"] = user_uuid

    return req_model


class TestTransfers(BaseTest):
    @mark.asyncio
    async def test_token_transfer_admin(
            self,
            approve_request,
            client,
            mock_kc_client_wrapper,
            request_base_body,
            post_json_admin_header
    ):
        """
        Test token transfer is accessible by admin users
        """
        response = await client.post(
            "/datasets/token_transfer",
            json=request_base_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201, response.json()
        assert list(response.json().keys()) == ["token"]

    @mark.asyncio
    async def test_token_transfer_admin_dataset_name(
            self,
            approve_request,
            client,
            request_base_body_name,
            post_json_admin_header,
            mock_kc_client_wrapper
    ):
        """
        Test token transfer is accessible by admin users
        """
        response = await client.post(
            "/datasets/token_transfer",
            json=request_base_body_name,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert list(response.json().keys()) == ["token"]

    @mark.asyncio
    async def test_token_transfer_admin_missing_requester_email_fails(
            self,
            client,
            request_base_body,
            post_json_admin_header,
            mock_kc_client_wrapper
    ):
        """
        Test token transfer fails if the requester's email is not provided
        """
        request_base_body["requested_by"].pop("email")
        response = await client.post(
            "/datasets/token_transfer",
            json=request_base_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    @mark.asyncio
    async def test_token_transfer_admin_dataset_not_found(
            self,
            client,
            request_base_body,
            post_json_admin_header,
            mock_kc_client_wrapper
    ):
        """
        Test token transfer fails on an non-existing dataset
        """
        request_base_body["dataset_id"] = 5012
        response = await client.post(
            "/datasets/token_transfer",
            json=request_base_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json() == {"error": "Dataset 5012 does not exist"}

    @mark.asyncio
    async def test_token_transfer_admin_dataset_by_name_not_found(
            self,
            client,
            request_base_body_name,
            post_json_admin_header,
            mock_kc_client_wrapper
    ):
        """
        Test token transfer fails on an non-existing dataset
        """
        request_base_body_name["dataset_name"] = "fake_dataset"
        response = await client.post(
            "/datasets/token_transfer",
            json=request_base_body_name,
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json() == {"error": "Dataset fake_dataset does not exist"}

    @mark.asyncio
    async def test_token_transfer_standard_user(
            self,
            client,
            request_base_body,
            post_json_user_header,
            mock_kc_client_wrapper,
            base_kc_mock_args
    ):
        """
        Test token transfer is accessible by admin users
        """
        base_kc_mock_args.is_token_valid.return_value = False
        response = await client.post(
            "/datasets/token_transfer",
            json=request_base_body,
            headers=post_json_user_header
        )
        assert response.status_code == 403

    @mark.asyncio
    async def test_transfer_does_nothing_same_request(
            self,
            client,
            post_json_admin_header,
            access_request,
            mock_kc_client_wrapper,
            approve_request,
            request_model_body,
            request_base_body,
            dataset,
            db_session
        ):
        """
        Tests that a duplicate request is not accepted.
        """
        await RequestModel(**request_model_body).add(db_session)

        response = await client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            json=request_base_body
        )
        assert response.status_code == 400
        assert response.json()["error"] == 'User already belongs to the active project project1'

    @mark.asyncio
    async def test_transfer_does_not_override_existing(
            self,
            client,
            post_json_admin_header,
            access_request,
            mock_kc_client_wrapper,
            approve_request,
            request_model_body,
            request_base_body,
            dataset,
            db_session
        ):
        """
        Tests that a duplicate, or a time-overlapping request
        is not accepted.
        """
        await RequestModel(**request_model_body).add(db_session)
        request_base_body["proj_end"] = (
            datetime.strptime(request_base_body["proj_end"], "%Y-%m-%d") + timedelta(days=20)
        ).strftime("%Y-%m-%d")

        response = await client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            json=request_base_body
        )
        assert response.status_code == 400

    @mark.asyncio
    async def test_transfer_successful_same_name_ds_different_time(
            self,
            client,
            post_json_admin_header,
            access_request,
            approve_request,
            mock_kc_client_wrapper,
            request_model_body,
            request_base_body,
            dataset,
            db_session
        ):
        """
        Tests that a duplicate, not time-overlapping request
        is accepted with same ds and project name.
        """
        request_model_body["proj_end"] = datetime.now().date()
        await RequestModel(**request_model_body).add(db_session)
        request_base_body["proj_start"] = (
            datetime.strptime(request_base_body["proj_end"], "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")

        response = await client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            json=request_base_body
        )
        assert response.status_code == 201

    @mark.asyncio
    async def test_transfer_only_one_ds_per_project(
            self,
            client,
            post_json_admin_header,
            access_request,
            mock_kc_client_wrapper,
            approve_request,
            request_model_body,
            request_base_body,
            dataset,
            dataset_oracle,
            db_session
        ):
        """
        Tests that only one dataset per active project is allowed.
        """
        await RequestModel(**request_model_body).add(db_session)
        request_base_body["dataset_id"] = dataset_oracle.id

        response = await client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            json=request_base_body
        )
        assert response.status_code == 400

    @mark.asyncio
    async def test_transfer_deleted_if_exception_raised(
            self,
            client,
            post_json_admin_header,
            access_request,
            mock_kc_client_wrapper,
            request_model_body,
            request_base_body,
            dataset,
            base_kc_mock_args,
            dataset_oracle
        ):
        """
        Tests that the entry is deleted when creating the permission
        in case something goes wrong on approve()
        """
        request_base_body["dataset_id"] = dataset_oracle.id

        base_kc_mock_args.get_user_by_email.side_effect = KeycloakError("error")

        response = await client.post(
            "/datasets/token_transfer",
            headers=post_json_admin_header,
            json=request_base_body
        )
        assert response.status_code == 500
        assert await self.run_query(select(func.count(RequestModel.id)).where(
            RequestModel.title == request_base_body["title"],
            RequestModel.project_name == request_base_body["project_name"],
        ), "one") == 0
