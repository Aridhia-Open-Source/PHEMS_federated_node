import os
import json
import os
from kubernetes.client.exceptions import ApiException
from sqlalchemy import select
from unittest import mock
from sqlalchemy.exc import ProgrammingError, OperationalError
from unittest import mock
from unittest.mock import Mock

from app.helpers.db import db
from app.helpers.exceptions import KeycloakError
from app.models.dataset import Dataset
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from tests.conftest import sample_ds_body
from app.helpers.exceptions import KeycloakError

missing_dict_cata_message = {"error": "Missing field. Make sure \"catalogue\" and \"dictionaries\" entries are there"}


class MixinTestDataset:
    expected_namespaces = [os.getenv("DEFAULT_NAMESPACE"), os.getenv("TASK_NAMESPACE")]
    hostname = os.getenv("PUBLIC_URL")

    def run_query(self, query):
        """
        Helper to run query through the ORM
        """
        return db.session.execute(query).all()

    def assert_datasets_by_name(self, dataset_name:str, count:int = 1):
        """
        Just to reduce duplicate code, use the ILIKE operator
        on the query to match case insensitive datasets name
        """
        assert Dataset.query.filter(Dataset.name.ilike(dataset_name)).count() == count

    def post_dataset(
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
        response = client.post(
            "/datasets/",
            data=json.dumps(data_body),
            headers=headers
        )
        assert response.status_code == code, response.data.decode()
        return response.json


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
        assert response.json == {
            "datasets": [
                self.expected_ds_entry(dataset)
            ]
        }

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
        assert response.json == {"error": "Could not find project"}

    @mock.patch('app.datasets_api.Request.add')
    @mock.patch('app.helpers.wrappers.Keycloak')
    @mock.patch('app.datasets_api.Request.approve', return_value={"token": "token"})
    def test_get_dataset_by_id_project_approved(
            self,
            req_add_mock,
            KeycloakMock,
            req_approve_mock,
            mocker,
            post_json_admin_header,
            request_base_body,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns 200 for project-approved users
        """
        KeycloakMock.return_value.is_token_valid.return_value = True
        KeycloakMock.return_value.decode_token.return_value = {"username": "test_user", "sub": "123-123abc"}
        KeycloakMock.return_value.exchange_global_token.return_value = ""

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
            "project-name": request_base_body["project_name"]
        })
        assert response.status_code == 200, response.json
        assert response.json == self.expected_ds_entry(dataset)

    @mock.patch('app.datasets_api.Request.approve', return_value={"token": "somejwttoken"})
    def test_get_dataset_by_id_project_non_approved(
            self,
            req_mock,
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
        assert response.json == {"error": "Could not find project"}

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


class TestPostDataset(MixinTestDataset):
    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_is_successful(
            self,
            ds_add_mock,
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
        self.post_dataset(client, post_json_admin_header, data_body)

        self.assert_datasets_by_name(data_body['name'])

        query = self.run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query)== 1

        for d in data_body["dictionaries"]:
            query = self.run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
            assert len(query)== 1

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_fails_with_same_name_case_sensitive(
            self,
            ds_add_mock,
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
        self.post_dataset(client, post_json_admin_header, data_body, 500)

        self.assert_datasets_by_name(data_body['name'])

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_with_url_encoded_name(
            self,
            ds_add_mock,
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
        new_ds = self.post_dataset(client, post_json_admin_header, data_body)

        self.assert_datasets_by_name("test dataset")

        response = client.get("/datasets/" + data_body['name'], headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == {
            "id": new_ds["dataset_id"],
            "name": "test dataset",
            "host": data_body["host"],
            "port": 5432,
            "type": "postgres",
            "slug": "test-dataset",
            "extra_connection_args": None,
            "url": f"https://{os.getenv("PUBLIC_URL")}/datasets/test-dataset"
        }

    def test_post_dataset_mssql_type(
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
        self.post_dataset(client, post_json_admin_header, data_body)

        query = self.run_query(select(Dataset).where(Dataset.name == data_body["name"].lower(), Dataset.type == "mssql"))
        assert len(query) == 1

    def test_post_dataset_with_extra_args(
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
        self.post_dataset(client, post_json_admin_header, data_body)

        ds = Dataset.query.filter(
            Dataset.name == data_body["name"].lower(),
            Dataset.extra_connection_args == data_body['extra_connection_args']
        ).one_or_none()
        assert ds is not None

    def test_post_dataset_invalid_type(
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
        resp = self.post_dataset(client, post_json_admin_header, data_body, code=400)
        assert resp["error"] == "DB type invalid is not supported."

        query = self.run_query(select(Dataset).where(Dataset.name == data_body["name"], Dataset.type == "mssql"))
        assert len(query) == 0

    def test_post_dataset_fails_k8s_secrets(
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
            'app.models.dataset.KubernetesClient.create_namespaced_secret',
            Mock(
                    side_effect=ApiException(status=500, reason="Failed")
            )
        )
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        self.post_dataset(client, post_json_admin_header, data_body, 400)

        query = self.run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 0

        self.assert_datasets_by_name(data_body['name'], count=0)

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_k8s_secrets_exists(
            self,
            ds_add_mock,
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
            'app.models.dataset.KubernetesClient',
            return_value=Mock(
                create_namespaced_secret=Mock(
                    side_effect=ApiException(status=409, reason="Conflict")
                )
            )
        )
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        self.post_dataset(client, post_json_admin_header, data_body)

        self.assert_datasets_by_name(data_body['name'])

    @mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
    def test_post_dataset_is_unsuccessful_non_admin(
            self,
            kc_tv_mock,
            post_json_user_header,
            client,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is not successful for non-admin users
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        self.post_dataset(client, post_json_user_header, data_body, 403)

        query = self.run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 0
        self.assert_datasets_by_name(data_body['name'], count=0)

        query = self.run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query)== 0


        for d in data_body["dictionaries"]:
            query = self.run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
            assert len(query)== 0

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_with_duplicate_dictionaries_fails(
            self,
            ds_add_mock,
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
        data_body["dictionaries"] += data_body["dictionaries"]

        response = self.post_dataset(client, post_json_admin_header, data_body, 500)
        assert response == {'error': 'Record already exists'}

        # Make sure any db entry is created
        query = self.run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 0
        self.assert_datasets_by_name(data_body['name'], count=0)

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_with_empty_dictionaries_succeeds(
            self,
            ds_add_mock,
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
        query_ds = self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        self.assert_datasets_by_name(data_body['name'])
        query = self.run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 1
        query = self.run_query(select(Dictionary).where(Dictionary.dataset_id == query_ds["dataset_id"]))
        assert len(query) == 0

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_with_wrong_dictionaries_format(
            self,
            ds_add_mock,
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
        response = self.post_dataset(client, post_json_admin_header, data_body, 400)
        assert response == {'error': 'dictionaries should be a list.'}

        # Make sure any db entry is created
        query = self.run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 0
        self.assert_datasets_by_name(data_body['name'], count=0)

        query = self.run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 0
        query = self.run_query(select(Dictionary).where(Dictionary.table_name == data_body["dictionaries"]["table_name"]))
        assert len(query) == 0

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_datasets_with_same_dictionaries_succeeds(
            self,
            ds_add_mock,
            post_json_admin_header,
            client,
            login_user,
            dataset,
            dataset_post_body
        ):
        """
        /datasets POST is successful with same catalogues and dictionaries
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs23'
        self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure db entries are created
        self.assert_datasets_by_name(data_body['name'])

        query = self.run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 1

        for d in data_body["dictionaries"]:
            query = self.run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
            assert len(query) == 1

        # Creating second DS
        data_body["name"] = "Another DS"
        ds_resp = self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        self.assert_datasets_by_name(data_body['name'])

        query = self.run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 2

        for d in data_body["dictionaries"]:
            query = self.run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
            assert len(query) == 2

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_with_catalogue_only(
            self,
            ds_add_mock,
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
        query_ds = self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        self.assert_datasets_by_name(data_body['name'])
        query = self.run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 1
        query = self.run_query(select(Dictionary).where(Dictionary.dataset_id == query_ds["dataset_id"]))
        assert len(query) == 0

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_with_dictionaries_only(
            self,
            ds_add_mock,
            post_json_admin_header,
            dataset,
            client,
            login_user,
            dataset_post_body
        ):
        """
        /datasets POST with dictionary but no catalogue is successful
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs22'
        data_body.pop("catalogue")
        query_ds = self.post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        self.assert_datasets_by_name(data_body['name'])

        query = self.run_query(select(Catalogue).where(Catalogue.dataset_id == query_ds["dataset_id"]))
        assert len(query) == 0
        for d in data_body["dictionaries"]:
            query = self.run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
            assert len(query)== 1


class TestPatchDataset(MixinTestDataset):
    @mock.patch('app.models.dataset.Keycloak.patch_resource', return_value=Mock())
    def test_patch_dataset_name_is_successful(
            self,
            mock_kc_patch,
            dataset,
            post_json_admin_header,
            client,
            k8s_client
    ):
        """
        Tests that the PATCH request works as intended
        by changing an existing dataset's name.
        Also asserts that the appropriate keycloak method
        is invoked
        """
        ds_old_name = dataset.name
        data_body = {"name": "new_name"}

        response = client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        ds = Dataset.query.filter(Dataset.id == dataset.id).one_or_none()
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

        mock_kc_patch.assert_called_with(
            f'{dataset.id}-{ds_old_name}',
            **{'displayName': f'{dataset.id} - new_name','name': f'{dataset.id}-new_name'}
        )

    @mock.patch('app.models.dataset.Keycloak.patch_resource', return_value=Mock())
    @mock.patch('app.datasets_api.Keycloak', return_value=Mock())
    def test_patch_dataset_name_with_dars(
            self,
            mock_kc_patch_api,
            mock_kc_patch,
            dataset,
            post_json_admin_header,
            client,
            access_request,
            dar_user,
            k8s_client
    ):
        """
        Tests that the PATCH request works as intended
        by changing an existing dataset's name.
        Also asserts that the appropriate keycloak method
        is invoked for each DAR client in keycloak
        """
        ds_old_name = dataset.name
        data_body = {"name": "new_name"}
        expected_client = f'Request {dar_user} - {dataset.host}'

        mock_kc_patch_api.return_value.patch_resource.return_value = Mock()

        response = client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        ds = Dataset.query.filter(Dataset.id == dataset.id).one_or_none()
        assert ds.name == "new_name"

        mock_kc_patch.assert_called_with(
            f'{dataset.id}-{ds_old_name}',
            **{'displayName': f'{dataset.id} - new_name','name': f'{dataset.id}-new_name'}
        )
        mock_kc_patch_api.assert_any_call(**{'client':expected_client})
        mock_kc_patch_api.return_value.patch_resource.assert_called_with(
            f'{dataset.id}-{ds_old_name}',
            **{'displayName': f'{dataset.id} - new_name','name': f'{dataset.id}-new_name'}
        )

    def test_patch_dataset_credentials_is_successful(
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
        response = client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 204

        expected_body = k8s_client["read_namespaced_secret_mock"].return_value
        for ns in self.expected_namespaces:
            k8s_client["read_namespaced_secret_mock"].assert_any_call(
                expected_secret_name,
                ns, pretty='pretty'
            )
            k8s_client["patch_namespaced_secret_mock"].assert_any_call(
                **{'name':expected_secret_name, 'namespace':ns, 'body': expected_body}
            )

    def test_patch_dataset_fails_on_k8s_error(
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

        k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(reason="Error occurred")

        response = client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        ds = Dataset.query.filter(Dataset.id == dataset.id).one_or_none()
        assert ds.name == ds_old_name

    @mock.patch('app.models.dataset.Keycloak.patch_resource', side_effect=KeycloakError("Failed to patch the resource"))
    def test_patch_dataset_fails_on_keycloak_update(
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
        ds_old_name = dataset.name
        response = client.patch(
            f"/datasets/{dataset.id}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 500, response.data
        ds = Dataset.query.filter(Dataset.id == dataset.id).one_or_none()
        assert ds.name == ds_old_name

    @mock.patch('app.models.dataset.Keycloak.patch_resource', side_effect=KeycloakError("Failed to patch the resource"))
    def test_patch_dataset_not_found(
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
        response = client.patch(
            f"/datasets/{dataset.id + 1}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 404

    def test_admin_get_dictionary_table_dataset_not_found(
            self,
            client,
            dataset,
            simple_admin_header
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        response = client.get(
            "/datasets/100/dictionaries/test",
            headers=simple_admin_header
        )
        assert response.status_code == 404


class TestBeacon:
    def test_beacon_available_to_admin(
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
        response = client.post(
            "/datasets/selection/beacon",
            json={
                "query": "SELECT * FROM table_name",
                "dataset_id": dataset.id
            },
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.json['result'] == 'Ok'

    def test_beacon_available_to_admin_invalid_query(
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
        response = client.post(
            "/datasets/selection/beacon",
            json={
                "query": "SELECT * FROM table",
                "dataset_id": dataset.id
            },
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        assert response.json['result'] == 'Invalid'

    def test_beacon_connection_failed(
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
        response = client.post(
            "/datasets/selection/beacon",
            json={
                "query": "SELECT * FROM table",
                "dataset_id": dataset.id
            },
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        assert response.json['error'] == 'Could not connect to the database'
