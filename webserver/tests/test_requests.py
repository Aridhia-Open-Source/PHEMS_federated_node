import pytest
import json
import requests
import os
from datetime import datetime as dt, timedelta
from sqlalchemy import update
from app.models.request import RequestModel
from app.helpers.keycloak import Keycloak
from tests.base_test_class import BaseTest

@pytest.fixture
def request_base_body():
    return {
        "title": "Test Task",
        "project_name": "project1",
        "requested_by": { "email": "test@test.com" },
        "description": "First task ever!",
        "proj_start": dt.now().date().strftime("%Y-%m-%d"),
        "proj_end": (dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    }

@pytest.mark.skip("The requests/ endpoints are deactivated for the time being")
class TestRequests(BaseTest):
    async def create_request(self, client, body:dict, header:dict, status_code=201):
        """
        Common function to handle a request and check for a status_code
        """
        response = await client.post(
            "/requests/",
            data=json.dumps(body),
            headers=header
        )
        assert response.status_code == status_code, response.data.decode()
        return response.json

    async def approve_request(self, client, req_id:str, header:dict, status_code=201):
        """
        Common function to send an approve request.
        """
        response = await client.post(
            f"/requests/{req_id}/approve",
            headers=header
        )
        assert response.status_code == status_code, response.data.decode()
        return response.json

    async def test_can_list_requests(
            self,
            client,
            simple_admin_header,
            access_request
    ):
        """
        Tests for admin user being able to see the list of open requests
        """
        response = await client.get('/requests/?status=pending', headers=simple_admin_header)
        assert response.status_code == 200

    async def test_cannot_list_requests(
            self,
            client,
            simple_user_header
    ):
        """
        Tests for non-admin user not being able to see the list of open requests
        """
        response = await client.get('/requests/?status=pending', headers=simple_user_header)
        assert response.status_code == 401

    async def test_create_request_fails_on_missing_email(
            self,
            request_base_body,
            post_json_admin_header,
            dataset,
            client
        ):
        """
        Test the request fails if the requester's email is missing
        """
        request_base_body["dataset_id"] = dataset.id
        request_base_body["requested_by"].pop("email")

        await self.create_request(client, request_base_body, post_json_admin_header, 500)

    async def test_create_request_fails_on_missing_dataset(
            self,
            request_base_body,
            post_json_admin_header,
            client
        ):
        """
        Test the request fails if the dataset id is not found
        """
        request_base_body["dataset_id"] = 5012
        response = await self.create_request(client, request_base_body, post_json_admin_header, 404)
        assert response == {"error": "Dataset with id 5012 does not exist"}

    async def test_approve_non_existing_dar_id(
            self,
            simple_admin_header,
            client,
        ):
        """
        Test the approval of a non existent request returns a 404
        """
        response_approval = await self.approve_request(client, 12354, simple_admin_header, 404)
        assert response_approval == {'error': 'Data Access RequestModel 12354 not found'}

    async def test_create_request_and_approve_is_successful(
            self,
            simple_admin_header,
            dataset,
            client,
            access_request
        ):
        """
        Test the whole process:
            - submit request
            - approve it
            - check for few keycloak resources
            - check access to endpoints
            - delete KC client
        """
        email_req = json.loads(access_request.requested_by)["email"]
        response_approval = await self.approve_request(client, access_request.id, simple_admin_header)
        kc_client = await Keycloak.create(f"RequestModel {email_req} - {access_request.project_name}")
        assert kc_client.get_resource(f"{dataset.id}-{dataset.name}") is not None

        response_ds = await client.get(
            f"/datasets/{dataset.id}",
            headers={
                "Authorization": f"Bearer {response_approval["token"]}",
                "project_name": access_request.project_name
            }
        )
        assert response_ds.status_code == 200

        # Cleanup
        requests.delete(
            f'{os.getenv("KEYCLOAK_URL")}/admin/realms/FederatedNode/clients/{kc_client.client_id}',
            headers={"Authorization": f"Bearer {kc_client.admin_token}"}
        )

    async def test_create_request_non_admin_is_not_successful(
            self,
            request_base_body,
            post_json_user_header,
            dataset,
            client
        ):
        """
        /requests POST returns 401 when an unauthorized user requests it
        """
        request_base_body["dataset_id"] = dataset.id
        await self.create_request(client, request_base_body, post_json_user_header, 401)

    async def test_approve_request_already_approved(
            self,
            simple_admin_header,
            client,
            access_request
        ):
        """
        Test the request fails if the dataset id is not found
        """
        response_approval = await self.approve_request(client, access_request.id, simple_admin_header)
        response_approval = await self.approve_request(client, access_request.id, simple_admin_header, 200)
        assert response_approval == {"message": "RequestModel already approved"}

    async def test_approve_request_already_denied(
            self,
            simple_admin_header,
            client,
            access_request
        ):
        """
        Test the request fails if the dataset id is not found
        """
        query = update(RequestModel).\
            where(RequestModel.id == access_request.id).\
            values(status=RequestModel.STATUSES["denied"])
        self.db_session.execute(query)
        self.db_session.commit()
        response_approval = await self.approve_request(client, access_request.id, simple_admin_header, 500)
        assert response_approval == {"error": "RequestModel was denied already"}

    async def test_create_request_with_same_project_is_successful(
            self,
            request_base_body,
            post_json_admin_header,
            simple_admin_header,
            dataset,
            dataset_oracle,
            client
        ):
        """
        Test the whole process:
            - submit request
            - approve it
            - submit request with same project
            - approve it
            - delete KC clients
        """
        request_base_body["dataset_id"] = dataset.id
        response_req = await self.create_request(client, request_base_body, post_json_admin_header)
        req_id = response_req['request_id']

        await self.approve_request(client, req_id, simple_admin_header)
        kc_client = await Keycloak.create(f"RequestModel {request_base_body["requested_by"]["email"]} - {request_base_body["project_name"]}")
        assert kc_client.get_resource(f"{dataset.id}-{dataset.name}") is not None

        # Second request
        request_base_body["dataset_id"] = dataset_oracle.id
        response_req = await self.create_request(client, request_base_body, post_json_admin_header)
        req_id = response_req['request_id']

        await self.approve_request(client, req_id, simple_admin_header)
        kc_client2 = await Keycloak.create(f"RequestModel {request_base_body["requested_by"]["email"]} - {request_base_body["project_name"]}")
        assert kc_client2.get_resource(f"{dataset_oracle.id}-{dataset_oracle.name}") is not None

        # Cleanup
        for cl_id in [kc_client, kc_client2]:
            requests.delete(
                f'{os.getenv("KEYCLOAK_URL")}/admin/realms/FederatedNode/clients/{cl_id.client_id}',
                headers={"Authorization": f"Bearer {cl_id.admin_token}"}
            )

    async def test_create_request_with_expired_project(
            self,
            request_base_body,
            post_json_admin_header,
            simple_admin_header,
            dataset,
            client
        ):
        """
        Test the whole process:
            - submit request
            - approve it
            - token returned won't allow access to the dataset
            - delete KC clients
        """
        request_base_body["dataset_id"] = dataset.id
        request_base_body["proj_start"] = (dt.now().date() - timedelta(days=2)).strftime("%Y-%m-%d")
        request_base_body["proj_end"] = (dt.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")

        response_req = await self.create_request(client, request_base_body, post_json_admin_header)
        req_id = response_req['request_id']

        response_approval = await self.approve_request(client, req_id, simple_admin_header)
        kc_client = await Keycloak.create(f"RequestModel {request_base_body["requested_by"]["email"]} - {request_base_body["project_name"]}")
        assert kc_client.get_resource(f"{dataset.id}-{dataset.name}") is not None


        response_ds = await client.get(
            f"/datasets/{dataset.id}",
            headers={
                "Authorization": f"Bearer {response_approval["token"]}",
                "project_name": request_base_body["project_name"]
            }
        )
        assert response_ds.status_code == 401
        # Cleanup
        requests.delete(
            f'{os.getenv("KEYCLOAK_URL")}/admin/realms/FederatedNode/clients/{kc_client.client_id}',
            headers={"Authorization": f"Bearer {kc_client.admin_token}"}
        )

    async def test_create_request_with_conflicting_project_dates(
            self,
            request_base_body,
            post_json_admin_header,
            simple_admin_header,
            dataset,
            client
        ):
        """
        Test the whole process with project start date > project end date:
            - submit request
            - approve it
            - token returned won't allow access to the dataset
            - delete KC clients
        """
        request_base_body["dataset_id"] = dataset.id
        request_base_body["proj_start"] = dt.now().date().strftime("%Y-%m-%d")
        request_base_body["proj_end"] = (dt.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")

        response_req = await self.create_request(client, request_base_body, post_json_admin_header)
        req_id = response_req['request_id']

        response_approval = await self.approve_request(client, req_id, simple_admin_header)
        kc_client = await Keycloak.create(f"RequestModel {request_base_body["requested_by"]["email"]} - {request_base_body["project_name"]}")
        assert kc_client.get_resource(f"{dataset.id}-{dataset.name}") is not None


        response_ds = await client.get(
            f"/datasets/{dataset.id}",
            headers={
                "Authorization": f"Bearer {response_approval["token"]}",
                "project_name": request_base_body["project_name"]
            }
        )
        assert response_ds.status_code == 401
        # Cleanup
        requests.delete(
            f'{os.getenv("KEYCLOAK_URL")}/admin/realms/FederatedNode/clients/{kc_client.client_id}',
            headers={"Authorization": f"Bearer {kc_client.admin_token}"}
        )

    async def test_request_for_invalid_dataset_fails(
            self,
            request_base_body,
            post_json_admin_header,
            client
        ):
        """
        /requests POST with non-existent dataset would return a 404
        """
        request_base_body["dataset_id"] = 100
        response = await self.create_request(client, request_base_body, post_json_admin_header, 404)

        assert response == {"error": "Dataset with id 100 does not exist"}
        assert await RequestModel.get_all() == []
