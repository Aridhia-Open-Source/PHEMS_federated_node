import json
from unittest import mock

from app.helpers.exceptions import KeycloakError
from app.models.dataset import Dataset
from app.models.request import Request
from tests.datasets.datasets_mixin import MixinTestDataset


class TestDatasets(MixinTestDataset):
    def expected_ds_entry(self, dataset:Dataset):
        return {
            "id": dataset.id,
            "name": dataset.name,
            "host": dataset.host,
            "port": 5432,
            "auth_type": "standard",
            "type": "postgres",
            "url": f"https://{self.hostname}/datasets/{dataset.name}",
            "slug": dataset.name,
            "schema": None,
            "extra_connection_args": None
        }

    def test_get_all_datasets(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        Get all dataset is possible only for admin users
        """
        response = client.get("/datasets/", headers=simple_admin_header)

        assert response.status_code == 200
        assert response.json["items"] == [self.expected_ds_entry(dataset)]

    def test_get_url_returned_in_dataset_list_is_valid(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        Checks that GET the url field from the Datasets works
        """
        response = client.get(dataset.url, headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == self.expected_ds_entry(dataset)

    def test_get_all_datasets_no_token(
            self,
            client
        ):
        """
        Get all dataset fails if no token is provided
        """
        response = client.get("/datasets/")
        assert response.status_code == 401

    def test_get_all_datasets_does_not_fail_for_non_admin(
            self,
            simple_user_header,
            client,
            dataset
        ):
        """
        Get all dataset is possible for non-admin users
        """
        response = client.get("/datasets/", headers=simple_user_header)
        assert response.status_code == 200

    def test_get_dataset_by_id_200(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns a valid dictionary representation for admin users
        """
        response = client.get(f"/datasets/{dataset.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == self.expected_ds_entry(dataset)

    @mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
    def test_get_dataset_by_id_403(
            self,
            mock_token_valid,
            simple_user_header,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns 403 for non-approved users
        """
        response = client.get(f"/datasets/{dataset.id}", headers=simple_user_header)
        assert response.status_code == 403, response.json

    @mock.patch(
        'app.helpers.wrappers.Keycloak.exchange_global_token',
        side_effect=KeycloakError("Could not find project", 400)
    )
    def test_get_dataset_by_id_project_not_valid(
            self,
            kc_egt_mock,
            simple_user_header,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns 400 for non-existing project
        """
        header = simple_user_header.copy()
        header["project-name"] = "test project"
        response = client.get(f"/datasets/{dataset.id}", headers=header)
        assert response.status_code == 400
        assert response.json == {"error": "User does not belong to a valid project"}

    @mock.patch('app.datasets_api.Request.approve', return_value={"token": "token"})
    @mock.patch('app.datasets_api.Keycloak.get_user_by_email', return_value={"id": "id"})
    def test_get_dataset_by_id_project_approved(
            self,
            kc_user_mock,
            req_approve_mock,
            mocker,
            mocks_kc_tasks,
            post_json_admin_header,
            request_base_body,
            client,
            dataset,
            user_uuid
        ):
        """
        /datasets/{id} GET returns 200 for project-approved users
        """
        response = client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert "token" in response.json

        token = response.json["token"]
        req = Request.query.filter(
            Request.project_name == request_base_body["project_name"]
        ).one_or_none()
        mocks_kc_tasks["wrappers"].return_value.get_user_by_username.return_value = {"id": user_uuid}
        req.requested_by = user_uuid

        response = client.get(f"/datasets/{dataset.id}", headers={
            "Authorization": f"Bearer {token}",
            "project-name": request_base_body["project_name"]
        })
        assert response.status_code == 200, response.json
        assert response.json == self.expected_ds_entry(dataset)

    @mock.patch('app.helpers.keycloak.Keycloak.is_user_admin', return_value=False)
    @mock.patch('app.datasets_api.Request.approve', return_value={"token": "somejwttoken"})
    @mock.patch('app.datasets_api.Keycloak.get_user_by_email', return_value={"id": "id"})
    def test_get_dataset_by_id_project_non_approved(
            self,
            kc_user_mock,
            req_mock,
            mocks_is_admin,
            project_not_found,
            post_json_admin_header,
            request_base_body,
            login_user,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns 401 for non-approved users
        """
        response = client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert list(response.json.keys()) == ["token"]

        token = response.json["token"]
        response = client.get(f"/datasets/{dataset.id}", headers={
            "Authorization": f"Bearer {token}",
            "project-name": "test project"
        })
        assert response.status_code == 400
        assert response.json == {"error": "User does not belong to a valid project"}

    def test_get_dataset_by_id_404(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns 404 for a non-existent dataset
        """
        invalid_id = 100
        response = client.get(f"/datasets/{invalid_id}", headers=simple_admin_header)
        assert response.status_code == 404

    def test_get_dataset_by_name_200(
            self,
            simple_admin_header,
            dataset,
            client
        ):
        """
        /datasets/{name} GET returns a valid list
        """
        response = client.get(f"/datasets/{dataset.name}", headers=simple_admin_header)
        assert response.status_code == 200, response.json
        assert response.json == self.expected_ds_entry(dataset)

    def test_get_dataset_by_name_404(
            self,
            simple_admin_header,
            dataset,
            client
        ):
        """
        /datasets/{name} GET returns a valid list
        """
        response = client.get("/datasets/anothername", headers=simple_admin_header)
        assert response.status_code == 404
        assert response.json == {"error": "Dataset anothername does not exist"}
