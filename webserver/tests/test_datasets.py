import json
from kubernetes.client.exceptions import ApiException
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from unittest import mock
from unittest.mock import Mock

from app.helpers.db import db
from app.helpers.exceptions import KeycloakError
from app.models.dataset import Dataset
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from tests.conftest import sample_ds_body

missing_dict_cata_message = {"error": "Missing field. Make sure \"catalogue\" and \"dictionaries\" entries are there"}

def run_query(query):
    """
    Helper to run query through the ORM
    """
    return db.session.execute(query).all()

def post_dataset(
        client,
        headers,
        data_body=sample_ds_body,
        code=201
    ):
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


class TestDatasets:
    def test_get_all_datasets(
            self,
            simple_admin_header,
            client,
            dataset
        ):
        """
        Get all dataset is possible only for admin users
        """
        expected_ds_entry = {
            "id": dataset.id,
            "name": dataset.name,
            "host": dataset.host,
            "port": 5432
        }

        response = client.get("/datasets/", headers=simple_admin_header)

        assert response.status_code == 200
        assert response.json == {
            "datasets": [
                expected_ds_entry
            ]
        }

    def test_get_all_datasets_no_token(
            self,
            client
        ):
        """
        Get all dataset fails if no token is provided
        """
        response = client.get("/datasets/")
        assert response.status_code == 401

    def test_get_all_datasets_fail_for_non_admin(
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
        expected_ds_entry = {
            "id": dataset.id,
            "name": dataset.name,
            "host": dataset.host,
            "port": 5432
        }
        response = client.get(f"/datasets/{dataset.id}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == expected_ds_entry

    @mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
    def test_get_dataset_by_id_401(
            self,
            kc_valid_mock,
            simple_user_header,
            client,
            dataset
        ):
        """
        /datasets/{id} GET returns 401 for non-approved users
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
        assert response.json == {'host': dataset.host, 'id': dataset.id, 'name': dataset.name, 'port': dataset.port}

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
        expected_ds_entry = {
            "id": dataset.id,
            "name": dataset.name,
            "host": dataset.host,
            "port": 5432
        }
        response = client.get(f"/datasets/{dataset.name}", headers=simple_admin_header)
        assert response.status_code == 200
        assert response.json == expected_ds_entry

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
        post_dataset(client, post_json_admin_header, data_body)

        query = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 1
        query = run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query)== 1
        for d in data_body["dictionaries"]:
            query = run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
            assert len(query)== 1

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_fails_k8s_secrets(
            self,
            ds_add_mock,
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
            'kubernetes.client.CoreV1Api',
            return_value=Mock(
                create_namespaced_secret=Mock(
                    side_effect=ApiException(status=500, reason="Failed")
                )
            )
        )
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        post_dataset(client, post_json_admin_header, data_body, 400)

        query = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 0

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
            'kubernetes.client.CoreV1Api',
            return_value=Mock(
                create_namespaced_secret=Mock(
                    side_effect=ApiException(status=409, reason="Conflict")
                )
            )
        )
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        post_dataset(client, post_json_admin_header, data_body)

        query = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 1

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
        post_dataset(client, post_json_user_header, data_body, 403)

        query = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 0
        query = run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query)== 0
        for d in data_body["dictionaries"]:
            query = run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
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
        data_body["dictionaries"].append(
            {
                "table_name": "test",
                "description": "test description"
            }
        )
        response = post_dataset(client, post_json_admin_header, data_body, 500)
        assert response == {'error': 'Record already exists'}

        # Make sure any db entry is created
        query = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 0

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
        post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        query_ds = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query_ds) == 1
        query = run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 1
        query = run_query(select(Dictionary).where(Dictionary.dataset_id == query_ds[0][0].id))
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
        response = post_dataset(client, post_json_admin_header, data_body, 400)
        assert response == {'error': 'dictionaries should be a list.'}

        # Make sure any db entry is created
        query = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query) == 0
        query = run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 0
        query = run_query(select(Dictionary).where(Dictionary.table_name == data_body["dictionaries"]["table_name"]))
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
        post_dataset(client, post_json_admin_header, data_body)

        # Make sure db entries are created
        query = run_query(select(Dataset).where(Dataset.name == data_body['name']))
        assert len(query) == 1
        query = run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 1
        for d in data_body["dictionaries"]:
            query = run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
            assert len(query) == 1

        # Creating second DS
        data_body["name"] = "Another DS"
        ds_resp = post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        query = run_query(select(Dataset).where(Dataset.id == ds_resp["dataset_id"]))
        assert len(query) == 1
        query = run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 2
        for d in data_body["dictionaries"]:
            query = run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
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
        post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        query_ds = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query_ds) == 1
        query = run_query(select(Catalogue).where(Catalogue.title == data_body["catalogue"]["title"]))
        assert len(query) == 1
        query = run_query(select(Dictionary).where(Dictionary.dataset_id == query_ds[0][0].id))
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
        post_dataset(client, post_json_admin_header, data_body)

        # Make sure any db entry is created
        query_ds = run_query(select(Dataset).where(Dataset.name == data_body["name"]))
        assert len(query_ds) == 1
        query = run_query(select(Catalogue).where(Catalogue.dataset_id == query_ds[0][0].id))
        assert len(query) == 0
        for d in data_body["dictionaries"]:
            query = run_query(select(Dictionary).where(Dictionary.table_name == d["table_name"]))
            assert len(query)== 1


class TestDictionaries:
    """
    Collection of tests for dictionaries requests
    """
    def test_admin_get_dictionaries(
            self,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header
    ):
        """
        Check that admin can see the dictionaries for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/dictionaries",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        for i in range(0, len(data_body["dictionaries"])):
            assert response.json[i].items() >= data_body["dictionaries"][i].items()

    def test_admin_get_dictionaries_dataset_name(
            self,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header
    ):
        """
        Check that admin can see the dictionaries for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{data_body['name']}/dictionaries",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        for i in range(0, len(data_body["dictionaries"])):
            assert response.json[i].items() >= data_body["dictionaries"][i].items()

    def test_get_dictionaries_not_allowed_user(
            self,
            mocker,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_user_header
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the dictionaries for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = post_dataset(client, post_json_admin_header, data_body)

        mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/dictionaries",
            headers=simple_user_header
        )
        assert response.status_code == 403


class TestCatalogues:
    """
    Collection of tests for catalogues requests
    """
    def test_admin_get_catalogue(
            self,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header
    ):
        """
        Check that admin can see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/catalogue",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.json.items() >= data_body["catalogue"].items()

    def test_admin_get_catalogue_dataset_name(
            self,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header
    ):
        """
        Check that admin can see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{data_body['name']}/catalogue",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.json.items() >= data_body["catalogue"].items()

    def test_get_catalogue_not_allowed_user(
            self,
            mocker,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_user_header
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = post_dataset(client, post_json_admin_header, data_body)

        mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/catalogue",
            headers=simple_user_header
        )
        assert response.status_code == 403


class TestDictionaryTable:
    """
    Collection of tests for dictionaries/table requests
    """
    def test_admin_get_dictionary_table(
            self,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/dictionaries/test",
            headers=simple_admin_header
        )
        assert response.status_code == 200

    def test_admin_get_dictionary_table_dataset_name(
            self,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{data_body['name']}/dictionaries/test",
            headers=simple_admin_header
        )
        assert response.status_code == 200

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

    def test_unauth_user_get_dictionary_table(
            self,
            mocker,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_user_header
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = post_dataset(client, post_json_admin_header, data_body)

        mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/dictionaries/test",
            headers=simple_user_header
        )
        assert response.status_code == 403

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
