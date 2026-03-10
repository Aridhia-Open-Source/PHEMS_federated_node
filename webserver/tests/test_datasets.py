import os
import json
import os
from pytest import mark
from kubernetes.client.exceptions import ApiException
from sqlalchemy import func, select
from unittest import mock
from sqlalchemy.exc import ProgrammingError, OperationalError
from unittest import mock
from unittest.mock import Mock

from app.helpers.exceptions import KeycloakError
from app.models.dataset import Dataset
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from app.models.request import RequestModel
from tests.conftest import sample_ds_body
from app.helpers.exceptions import KeycloakError
from tests.base_test_class import BaseTest

missing_dict_cata_message = {"error": "Missing field. Make sure \"catalogue\" and \"dictionaries\" entries are there"}


class MixinTestDataset(BaseTest):
    expected_namespaces = [os.getenv("DEFAULT_NAMESPACE"), os.getenv("TASK_NAMESPACE")]
    hostname = os.getenv("PUBLIC_URL")

    async def assert_datasets_by_name(self, dataset_name:str, count:int = 1):
        """
        Just to reduce duplicate code, use the ILIKE operator
        on the query to match case insensitive datasets name
        """
        assert await self.run_query(select(func.count(Dataset.id)).filter(Dataset.name.ilike(dataset_name)), "one") == count

    async def post_dataset(
            self,
            client,
            headers,
            data_body=sample_ds_body,
            code=201
        ) -> dict:
        """
        Helper method that created a given dataset, if none specified
        uses dataset_post_body
        """
        response = await client.post(
            "/datasets",
            json=data_body,
            headers=headers
        )
        assert response.status_code == code, response.text
        return response.json()


class TestDatasets(MixinTestDataset):
    def expected_ds_entry(self, dataset:Dataset):
        return {
            "id": dataset.id,
            "name": dataset.name,
            "host": dataset.host,
            "port": 5432,
            "type": "postgres",
            "url": f"https://{self.hostname}/datasets/{dataset.name}",
            "slug": dataset.name,
            "schema_read": None,
            "schema_write": None,
            "repository": None,
            "extra_connection_args": None
        }

    @mark.asyncio
    async def test_get_all_datasets(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        Get all dataset is possible only for admin users
        """
        response = await client.get("/datasets", headers=simple_admin_header)

        assert response.status_code == 200
        assert response.json()["items"] == [self.expected_ds_entry(dataset)]

    @mark.asyncio
    async def test_get_url_returned_in_dataset_list_is_valid(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        Checks that GET the url field from the Datasets works
        """
        response = await client.get(dataset.url, headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json() == self.expected_ds_entry(dataset)

    @mark.asyncio
    async def test_get_all_datasets_no_token(
            self,
            client
        ):
        """
        Get all dataset fails if no token is provided
        """
        response = await client.get("/datasets")
        assert response.status_code == 401, response.json()

    @mark.asyncio
    async def test_get_all_datasets_does_not_fail_for_non_admin(
            self,
            simple_user_header,
            client,
            dataset
        ):
        """
        Get all dataset is possible for non-admin users
        """
        response = await client.get("/datasets", headers=simple_user_header)
        assert response.status_code == 200

    @mark.asyncio
    async def test_get_dataset_by_id_200(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns a valid dictionary representation for admin users
        """
        response = await client.get(f"/datasets/{dataset.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json() == self.expected_ds_entry(dataset)

    @mark.asyncio
    async def test_get_dataset_by_id_403(
            self,
            simple_user_header,
            client,
            dataset,
            mock_kc_client
        ):
        """
        /datasets/{id} GET returns 403 for non-approved users
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        response = await client.get(f"/datasets/{dataset.id}", headers=simple_user_header)
        assert response.status_code == 403, response.json()

    @mark.asyncio
    async def test_get_dataset_by_id_project_not_valid(
            self,
            simple_user_header,
            client,
            dataset,
            mock_kc_client
        ):
        """
        /datasets/{id} GET returns 400 for non-existing project
        """
        mock_kc_client["wrappers_kc"].return_value.has_user_roles.return_value = False
        mock_kc_client["wrappers_kc"].return_value.exchange_global_token.side_effect = KeycloakError("Could not find project", 400)
        header = simple_user_header.copy()
        header["project-name"] = "test project"
        response = await client.get(f"/datasets/{dataset.id}", headers=header)
        assert response.status_code == 400
        assert response.json() == {"error": "Could not find project"}

    @mock.patch('app.routes.datasets.RequestModel.approve', return_value={"token": "token"})
    @mark.asyncio
    async def test_get_dataset_by_id_project_approved(
            self,
            req_approve_mock,
            mock_kc_client,
            post_json_admin_header,
            request_base_body,
            client,
            dataset,
            user_uuid
        ):
        """
        /datasets/{id} GET returns 200 for project-approved users
        """
        response = await client.post(
            "/datasets/token_transfer",
            json=request_base_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert "token" in response.json()

        token = response.json()["token"]
        req = await self.run_query(select(RequestModel).where(
            RequestModel.project_name == request_base_body["project_name"]
        ), "one")
        mock_kc_client["wrappers_kc"].return_value.get_user_by_username.return_value = {"id": user_uuid}
        req.requested_by = user_uuid

        response = await client.get(f"/datasets/{dataset.id}", headers={
            "Authorization": f"Bearer {token}",
            "project-name": request_base_body["project_name"]
        })
        assert response.status_code == 200, response.json()
        assert response.json() == self.expected_ds_entry(dataset)

    @mock.patch('app.routes.datasets.RequestModel.approve', return_value={"token": "somejwttoken"})
    @mark.asyncio
    async def test_get_dataset_by_id_project_non_approved(
            self,
            req_mock,
            project_not_found,
            post_json_admin_header,
            request_base_body,
            client,
            dataset,
            mock_kc_client
        ):
        """
        /datasets/{id} GET returns 401 for non-approved users
        """
        response = await client.post(
            "/datasets/token_transfer",
            data=json.dumps(request_base_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        assert list(response.json().keys()) == ["token"]

        token = response.json()["token"]
        mock_kc_client["wrappers_kc"].return_value.is_user_admin.return_value = False
        response = await client.get(f"/datasets/{dataset.id}", headers={
            "Authorization": f"Bearer {token}",
            "project-name": "test project"
        })
        assert response.status_code == 400
        assert response.json() == {"error": "User does not belong to a valid project"}

    @mark.asyncio
    async def test_get_dataset_by_id_404(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns 404 for a non-existent dataset
        """
        invalid_id = 100
        response = await client.get(f"/datasets/{invalid_id}", headers=simple_admin_header)
        assert response.status_code == 404

    @mark.asyncio
    async def test_get_dataset_by_name_200(
            self,
            simple_admin_header,
            dataset,
            client
        ):
        """
        /datasets/{name} GET returns a valid list
        """
        response = await client.get(f"/datasets/{dataset.name}", headers=simple_admin_header)
        assert response.status_code == 200, response.json()
        assert response.json() == self.expected_ds_entry(dataset)

    @mark.asyncio
    async def test_get_dataset_by_name_404(
            self,
            simple_admin_header,
            dataset,
            client
        ):
        """
        /datasets/{name} GET returns a valid list
        """
        response = await client.get("/datasets/anothername", headers=simple_admin_header)
        assert response.status_code == 404
        assert response.json() == {"error": "Dataset anothername does not exist"}


class TestPostDataset(MixinTestDataset):
    @mark.asyncio
    async def test_post_dataset_is_successful(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is successful
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        await self.post_dataset(client, post_json_admin_header, data_body)

        await self.assert_datasets_by_name(data_body['name'])

        query = await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.title == data_body["catalogue"]["title"]), "one")
        assert query == 1

        for d in data_body["dictionaries"]:
            query = await self.run_query(select(func.count(Dictionary.id)).where(Dictionary.table_name == d["table_name"]), "one")
            assert query == 1

    @mark.asyncio
    async def test_post_dataset_fails_with_same_name_case_sensitive(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST fails if the ds name is the same with case-sensitive
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = data_body['name'].upper()
        await self.post_dataset(client, post_json_admin_header, data_body, 400)

        await self.assert_datasets_by_name(data_body['name'])

    @mark.asyncio
    async def test_post_dataset_with_url_encoded_name(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body,
            simple_admin_header
        ):
        """
        /datasets POST fails if the ds name is the same with case-sensitive
        """
        data_body = dataset_post_body.copy()

        data_body['name'] = "test%20dataset"
        new_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        await self.assert_datasets_by_name("test dataset")

        response = await client.get("/datasets/" + data_body['name'], headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json() == {
            "id": new_ds["id"],
            "name": "test dataset",
            "host": data_body["host"],
            "port": 5432,
            "type": "postgres",
            "slug": "test-dataset",
            "schema_read": None,
            "schema_write": None,
            "repository": None,
            "extra_connection_args": None,
            "url": f"https://{os.getenv("PUBLIC_URL")}/datasets/test-dataset"
        }

    @mark.asyncio
    async def test_post_dataset_mssql_type(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is successful with the type set
        to mssql as one of the supported engines
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        data_body['type'] = 'mssql'
        await self.post_dataset(client, post_json_admin_header, data_body)

        query = await self.run_query(select(func.count(Dataset.id)).where(Dataset.name == data_body["name"].lower(), Dataset.type == "mssql"), "one")
        assert query == 1

    @mark.asyncio
    async def test_post_dataset_with_extra_args(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is successful with the extra_connection_args set
        to a non null value
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        data_body['extra_connection_args'] = 'read_only=true'
        await self.post_dataset(client, post_json_admin_header, data_body)

        assert await self.run_query(
            select(func.count(Dataset.id)).filter_by(
                name=data_body["name"].lower(),
                extra_connection_args=data_body['extra_connection_args']
            )
        , "one") > 0

    @mark.asyncio
    async def test_post_dataset_with_existing_repo_linked(
            self,
            post_json_admin_header,
            client,
            dataset_with_repo,
            dataset_post_body
        ):
        """
        /datasets POST fails if the new dataset uses a repository that
        already has an association on an existing FN dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        data_body['repository'] = dataset_with_repo.repository
        resp = await self.post_dataset(client, post_json_admin_header, data_body, 400)
        assert resp["error"] == "Repository is already linked to another dataset. Please PATCH that dataset with repository: null"

        assert await self.run_query(
            select(func.count(Dataset.id)).filter_by(repository=dataset_with_repo.repository)
        , "one") > 0

    @mark.asyncio
    async def test_post_dataset_invalid_type(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is successful with the type set
        to something not supported
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        data_body['type'] = 'invalid'
        resp = await self.post_dataset(client, post_json_admin_header, data_body, code=400)
        assert resp["error"][0]["message"] == "Value error, DB type invalid is not supported."

        query = await self.run_query(select(func.count(Dataset.id)).where(Dataset.name == data_body["name"], Dataset.type == "mssql"), "one")
        assert query == 0

    @mark.asyncio
    async def test_post_dataset_fails_k8s_secrets(
            self,
            post_json_admin_header,
            client,
            k8s_config,
            dataset_post_body,
            mocker
        ):
        """
        /datasets POST fails if the k8s secrets cannot be created successfully
        """
        mocker.patch(
            'app.services.datasets.KubernetesClient.create_namespaced_secret',
            Mock(
                side_effect=ApiException(
                    http_resp=Mock(status=500, reason="Error", data="Failed")
                )
            )
        )
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        await self.post_dataset(client, post_json_admin_header, data_body, 500)

        query = await self.run_query(select(func.count(Dataset.id)).filter_by(name=data_body["name"]), "one")
        assert query == 0
        await self.assert_datasets_by_name(data_body['name'], count=0)

    @mark.asyncio
    async def test_post_dataset_k8s_secrets_exists(
            self,
            post_json_admin_header,
            client,
            k8s_config,
            dataset_post_body,
            mocker
        ):
        """
        /datasets POST is successful if the k8s secrets already exists
        """
        mocker.patch(
            'app.services.datasets.KubernetesClient',
            return_value=Mock(
                create_namespaced_secret=Mock(
                    side_effect=ApiException(status=409, reason="Conflict")
                )
            )
        )
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        await self.post_dataset(client, post_json_admin_header, data_body)

        await self.assert_datasets_by_name(data_body['name'])

    @mark.asyncio
    async def test_post_dataset_is_unsuccessful_non_admin(
            self,
            post_json_user_header,
            client,
            dataset,
            dataset_post_body,
            mock_kc_client
        ):
        """
        /datasets POST is not successful for non-admin users
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        await self.post_dataset(client, post_json_user_header, data_body, 403)

        query = await self.run_query(select(func.count(Dataset.id)).where(Dataset.name == data_body["name"]), "one")
        assert query == 0
        await self.assert_datasets_by_name(data_body['name'], count=0)

        query = await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.title == data_body["catalogue"]["title"]), "one")
        assert query == 0

        for d in data_body["dictionaries"]:
            query = await self.run_query(select(func.count(Dictionary.id)).where(Dictionary.table_name == d["table_name"]), "one")
            assert query == 0

    @mark.asyncio
    async def test_post_dataset_with_duplicate_dictionaries_fails(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body,
            mock_kc_client
        ):
        """
        /datasets POST is not successful
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs22'
        data_body["dictionaries"] += data_body["dictionaries"]

        response = await self.post_dataset(client, post_json_admin_header, data_body, 500)
        assert response == {'error': 'Record already exists'}

        # Make sure any db entry is created
        query = await self.run_query(select(func.count(Dataset.id)).where(Dataset.name == data_body["name"]), "one")
        assert query == 0
        await self.assert_datasets_by_name(data_body['name'], count=0)

    @mark.asyncio
    async def test_post_dataset_with_empty_dictionaries_succeeds(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is successful with dictionaries = []
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs22'
        data_body["dictionaries"] = []
        query_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        await self.assert_datasets_by_name(data_body['name'])
        query = await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.title == data_body["catalogue"]["title"]), "one")
        assert query == 1
        query = await self.run_query(select(func.count(Dictionary.id)).where(Dictionary.dataset_id == query_ds["id"]), "one")
        assert query == 0

    @mark.asyncio
    async def test_post_dataset_with_wrong_dictionaries_format(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is not successful
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs22'
        data_body["dictionaries"] = {
            "table_name": "test",
            "description": "test description"
        }
        response = await self.post_dataset(client, post_json_admin_header, data_body, 400)
        assert response["error"][0]["message"] == "Input should be a valid list"

        # Make sure any db entry is created
        query = await self.run_query(select(func.count(Dataset.id)).where(Dataset.name == data_body["name"]), "one")
        assert query == 0
        await self.assert_datasets_by_name(data_body['name'], count=0)

        query = await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.title == data_body["catalogue"]["title"]), "one")
        assert query == 0
        query = await self.run_query(select(func.count(Dictionary.id)).where(Dictionary.table_name == data_body["dictionaries"]["table_name"]), "one")
        assert query == 0

    @mark.asyncio
    async def test_post_datasets_with_same_dictionaries_succeeds(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is successful with same catalogues and dictionaries
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs23'
        await self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure db entries are created
        await self.assert_datasets_by_name(data_body['name'])

        query = await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.title == data_body["catalogue"]["title"]), "one")
        assert query == 1

        for d in data_body["dictionaries"]:
            query = await self.run_query(select(func.count(Dictionary.id)).where(Dictionary.table_name == d["table_name"]), "one")
            assert query == 1

        # Creating second DS
        data_body["name"] = "Another DS"
        ds_resp = await self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        await self.assert_datasets_by_name(data_body['name'])

        query = await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.title == data_body["catalogue"]["title"]), "one")
        assert query == 2

        for d in data_body["dictionaries"]:
            query = await self.run_query(select(func.count(Dictionary.id)).where(Dictionary.table_name == d["table_name"]), "one")
            assert query == 2

    @mark.asyncio
    async def test_post_dataset_with_catalogue_only(
            self,
            post_json_admin_header,
            dataset,
            client,
            dataset_post_body
        ):
        """
        /datasets POST with catalogue but no dictionary is successful
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs22'
        data_body.pop("dictionaries")
        query_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        await self.assert_datasets_by_name(data_body['name'])
        query = await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.title == data_body["catalogue"]["title"]), "one")
        assert query == 1
        query = await self.run_query(select(func.count(Dictionary.id)).where(Dictionary.dataset_id == query_ds["id"]), "one")
        assert query == 0

    @mark.asyncio
    async def test_post_dataset_with_dictionaries_only(
            self,
            post_json_admin_header,
            dataset,
            client,
            dataset_post_body
        ):
        """
        /datasets POST with dictionary but no catalogue is successful
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs22'
        data_body.pop("catalogue")
        query_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        await self.assert_datasets_by_name(data_body['name'])

        query = await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.dataset_id == query_ds["id"]), "one")
        assert query == 0
        for d in data_body["dictionaries"]:
            query = await self.run_query(select(func.count(Dictionary.id)).where(Dictionary.table_name == d["table_name"]), "one")
            assert query== 1


class TestPatchDataset(MixinTestDataset):
    @mark.asyncio
    async def test_patch_dataset_name_is_successful(
            self,
            dataset,
            post_json_admin_header,
            client,
            k8s_client,
            mock_kc_client
    ):
        """
        Tests that the PATCH request works as intended
        by changing an existing dataset's name.
        Also asserts that the appropriate keycloak method
        is invoked
        """
        ds_old_name = dataset.name
        data_body = {"name": "new_name"}

        response = await client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        ds: Dataset = await self.run_query(select(Dataset).filter(Dataset.id == dataset.id), "one_or_none")
        assert ds.name == "new_name"

        expected_body = k8s_client["read_namespaced_secret_mock"].return_value
        expected_secret_name = f'{dataset.host}-{ds_old_name.lower()}-creds'

        for ns in self.expected_namespaces:
            k8s_client["create_namespaced_secret_mock"].assert_any_call(
                ns, **{'body': expected_body, 'pretty': 'true'}
            )
            k8s_client["delete_namespaced_secret_mock"].assert_any_call(
                **{'namespace':ns, 'name':expected_secret_name}
            )

        mock_kc_client["dataset_kc"].return_value.patch_resource.assert_called_with(
            f'{dataset.id}-{ds_old_name}',
            **{'displayName': f'{dataset.id} - new_name','name': f'{dataset.id}-new_name'}
        )

    @mark.asyncio
    async def test_patch_dataset_name_with_dars(
            self,
            dataset,
            post_json_admin_header,
            client,
            access_request,
            dar_user,
            user_uuid,
            k8s_client,
            mock_kc_client
    ):
        """
        Tests that the PATCH request works as intended
        by changing an existing dataset's name.
        Also asserts that the appropriate keycloak method
        is invoked for each DAR client in keycloak
        """
        ds_old_name = dataset.name
        data_body = {"name": "new_name"}
        expected_client = f'RequestModel {dar_user} - {dataset.host}'

        mock_kc_client["datasets_route_kc"].return_value.patch_resource.return_value = Mock()
        mock_kc_client["datasets_route_kc"].return_value.get_user_by_id.return_value = {"email": dar_user}

        response = await client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        ds = await self.run_query(select(Dataset).filter(Dataset.id == dataset.id), "one_or_none")
        assert ds.name == "new_name"

        mock_kc_client["dataset_kc"].return_value.patch_resource.assert_called_with(
            f'{dataset.id}-{ds_old_name}',
            **{'displayName': f'{dataset.id} - new_name','name': f'{dataset.id}-new_name'}
        )
        mock_kc_client["datasets_route_kc"].assert_any_call(**{'client':expected_client})
        mock_kc_client["datasets_route_kc"].return_value.patch_resource.assert_called_with(
            f'{dataset.id}-{ds_old_name}',
            **{'displayName': f'{dataset.id} - new_name','name': f'{dataset.id}-new_name'}
        )

    @mark.asyncio
    async def test_patch_dataset_credentials_is_successful(
            self,
            dataset,
            post_json_admin_header,
            client,
            k8s_client
    ):
        """
        Tests that the PATCH request works as intended
        by changing an existing dataset's credential secret.
        Also asserts that the appropriate keycloak method
        is invoked
        """
        expected_secret_name = f'{dataset.host}-{dataset.name.lower()}-creds'
        data_body = {
            "username": "john",
            "password": "johnsmith"
        }
        response = await client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202

        expected_body = k8s_client["read_namespaced_secret_mock"].return_value
        for ns in self.expected_namespaces:
            k8s_client["read_namespaced_secret_mock"].assert_any_call(
                expected_secret_name,
                ns, pretty='pretty'
            )
            k8s_client["patch_namespaced_secret_mock"].assert_any_call(
                **{'name':expected_secret_name, 'namespace':ns, 'body': expected_body}
            )

    @mark.asyncio
    async def test_patch_dataset_fails_on_k8s_error(
            self,
            dataset,
            post_json_admin_header,
            client,
            k8s_client
    ):
        """
        Tests that the PATCH request returns a 400 in case
        k8s secret creation goes wrong
        """
        data_body = {"name": "new_name"}
        ds_old_name = dataset.name

        k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(
            http_resp=Mock(status=500, reason="Error", data="Error occurred")
        )

        response = await client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        ds = await self.run_query(select(Dataset).filter(Dataset.id == dataset.id), "one_or_none")
        assert ds.name == ds_old_name

    @mark.asyncio
    async def test_patch_dataset_fails_on_keycloak_update(
            self,
            dataset,
            post_json_admin_header,
            client,
            mock_kc_client
    ):
        """
        Tests that the PATCH request returns a 400 in case
        keycloak resource update goes wrong
        """
        mock_kc_client["dataset_kc"].return_value.patch_resource.side_effect=KeycloakError("Failed to patch the resource")
        data_body = {
            "name": "new_name"
        }
        ds_old_name = dataset.name
        response = await client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        ds = await self.run_query(select(Dataset).filter(Dataset.id == dataset.id), "one_or_none")
        assert ds.name == ds_old_name

    @mock.patch('app.services.datasets.Keycloak.patch_resource', side_effect=KeycloakError("Failed to patch the resource"))
    @mark.asyncio
    async def test_patch_dataset_not_found(
            self,
            mock_kc_patch,
            dataset,
            post_json_admin_header,
            client
    ):
        """
        Tests that the PATCH request returns a 400 in case
        keycloak resource update goes wrong
        """
        data_body = {
            "name": "new_name"
        }
        response = await client.patch(
            f"/datasets/{dataset.id + 1}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    @mark.asyncio
    async def test_admin_get_dictionary_table_dataset_not_found(
            self,
            client,
            dataset,
            simple_admin_header
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        response = await client.get(
            "/datasets/100/dictionaries/test",
            headers=simple_admin_header
        )
        assert response.status_code == 404


class TestBeacon:
    @mark.asyncio
    async def test_beacon_available_to_admin(
            self,
            client,
            post_json_admin_header,
            mocker,
            dataset
    ):
        """
        Test that the beacon endpoint is accessible to admin users
        """
        mocker.patch('app.helpers.query_validator.create_engine')
        mocker.patch(
            'app.helpers.query_validator.sessionmaker',
        ).__enter__.return_value = Mock()
        response = await client.post(
            "/datasets/selection/beacon",
            json={
                "query": "SELECT * FROM table_name",
                "dataset_id": dataset.id
            },
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json()['result'] == 'Ok'

    @mark.asyncio
    async def test_beacon_available_to_admin_invalid_query(
            self,
            client,
            post_json_admin_header,
            mocker,
            dataset
    ):
        """
        Test that the beacon endpoint is accessible to admin users
        """
        mocker.patch('app.helpers.query_validator.create_engine')
        mocker.patch(
            'app.helpers.query_validator.sessionmaker',
            side_effect = ProgrammingError(statement="", params={}, orig="error test")
        )
        response = await client.post(
            "/datasets/selection/beacon",
            json={
                "query": "SELECT * FROM table",
                "dataset_id": dataset.id
            },
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json()['result'] == 'Invalid'

    @mark.asyncio
    async def test_beacon_connection_failed(
            self,
            client,
            post_json_admin_header,
            mocker,
            dataset
    ):
        """
        Test that the beacon endpoint is accessible to admin users
        but returns an appropriate error message in case of connection
        failed
        """
        mocker.patch('app.helpers.query_validator.create_engine')
        mocker.patch(
            'app.helpers.query_validator.sessionmaker',
            side_effect = OperationalError(
                statement="Unable to connect: Adaptive Server is unavailable or does not exist",
                params={}, orig="error test"
            )
        )
        response = await client.post(
            "/datasets/selection/beacon",
            json={
                "query": "SELECT * FROM table",
                "dataset_id": dataset.id
            },
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        assert response.json()['error'] == 'Could not connect to the database'


class TestDeleteDataset(MixinTestDataset):
    @mark.asyncio
    async def test_delete_dataset_with_secrets(
            self,
            client,
            dataset,
            post_json_admin_header,
            k8s_client
    ):
        """
        Test to make sure the db entry and k8s secret are deleted
        """
        ds_id = dataset.id
        secret_name = dataset.get_creds_secret_name()
        response = await client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        k8s_client["delete_namespaced_secret_mock"].assert_called_with(
            secret_name, 'default'
        )

    @mark.asyncio
    async def test_delete_dataset_not_found(
            self,
            client,
            dataset,
            post_json_admin_header,
            k8s_client
    ):
        """
        Deleting a non existing dataset, returns a 404
        """
        ds_id = dataset.id + 1
        response = await client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        k8s_client["delete_namespaced_secret_mock"].assert_not_called()

    @mark.asyncio
    async def test_delete_dataset_with_secrets_error(
            self,
            client,
            dataset,
            post_json_admin_header,
            k8s_client
    ):
        """
        Test to make sure the db entry and k8s secret are
        not deleted if an exception is raised
        """
        ds_id = dataset.id
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(
            status=500, reason="failed"
        )

        response = await client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert await Dataset.get_by_id(self.db_session, ds_id, raise_if_not_found=False) is not None

    @mark.asyncio
    async def test_delete_dataset_with_secrets_not_found_error(
            self,
            client,
            dataset,
            post_json_admin_header,
            k8s_client
    ):
        """
        Test to make sure the db entry is deleted if the secret does
        not exist
        """
        ds_id = dataset.id
        k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(
            status=404, reason="failed"
        )

        response = await client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        self.db_session.expire_all()
        assert await Dataset.get_by_id(self.db_session, ds_id, raise_if_not_found=False) is None

    @mark.asyncio
    async def test_delete_dataset_with_catalougues(
            self,
            client,
            dataset,
            post_json_admin_header,
            catalogue,
            dictionary
    ):
        """
        Test to make sure the cascade deletion happens
        """
        ds_id = dataset.id
        response = await client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        assert await self.run_query(
                select(func.count(Catalogue.id)).where(Catalogue.dataset_id==ds_id), "one") == 0
        assert await self.run_query(
                select(func.count(Dictionary.id)).where(Dictionary.dataset_id==ds_id), "one") == 0

    @mark.asyncio
    async def test_delete_dataset_unauthorized(
            self,
            client,
            dataset,
            post_json_user_header,
            mock_kc_client
    ):
        """
        Tests that a non admin cannot delete a dataset
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        ds_id = dataset.id
        response = await client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_user_header
        )
        assert response.status_code == 403
