import os
from kubernetes.client.exceptions import ApiException
from sqlalchemy import select
from unittest import mock
from unittest.mock import Mock

from app.models.dataset import Dataset, SUPPORTED_AUTHS
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from tests.datasets.datasets_mixin import MixinTestDataset


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
            "auth_type": "standard",
            "schema": None,
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

    def test_post_dataset_kerberos_auth(
            self,
            post_json_admin_header,
            client,
            dataset,
            dataset_kerberos_post_body,
            kerberos_secret_read
        ):
        """
        /datasets POST is successful with the auth type won't
        check for credentials in the body, and will still accept that
        """
        self.post_dataset(client, post_json_admin_header, dataset_kerberos_post_body)

        query = self.run_query(select(Dataset).where(Dataset.name == dataset_kerberos_post_body["name"].lower(), Dataset.type == "mssql"))
        assert len(query) == 1

    def test_post_dataset_kerberos_auth_no_secret(
            self,
            post_json_admin_header,
            client,
            dataset_kerberos_post_body,
            kerberos_secret_read
        ):
        """
        /datasets POST is successful with the auth type won't
        check for credentials in the body, but will fail with no secret name provided
        """
        data_body = {
            "name": "TestDs78",
            "type": 'mssql',
            "host": "something",
            "auth_type": "kerberos",
            "username": "something"
        }

        resp = self.post_dataset(client, post_json_admin_header, data_body, 400)
        assert resp["error"] == "With kerberos auth_type, a secret containing krb5.conf and principal.keytab keys is needed"

    def test_post_dataset_invalid_auth(
            self,
            post_json_admin_header,
            client,
            dataset,
        ):
        """
        /datasets POST is successful with the auth type won't
        check for credentials in the body, and will still accept that
        """
        data_body = {
            "name": "TestDs78",
            "type": 'mssql',
            "host": "something",
            "auth_type": "invalid"
        }

        resp = self.post_dataset(client, post_json_admin_header, data_body, code=400)
        assert resp == {"error": f"invalid is not supported. Try one of {SUPPORTED_AUTHS}"}

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
            k8s_client,
            dataset_post_body,
            mocker
        ):
        """
        /datasets POST fails if the k8s secrets cannot be created successfully
        """
        k8s_client["create_namespaced_secret_mock"].side_effect=ApiException(status=500, reason="Failed")
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
                ),
                read_namespaced_config_map=Mock(
                    return_value=Mock(data={"krb5.conf": "", "principal.keytab": ""})
                )
            )
        )
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        self.post_dataset(client, post_json_admin_header, data_body)

        self.assert_datasets_by_name(data_body['name'])

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_kerberos_missing_fields(
            self,
            ds_add_mock,
            post_json_admin_header,
            client,
            k8s_config,
            dataset_kerberos_post_body,
            mocker
        ):
        """
        /datasets POST is not successful if the cm provided is missing
        required keys
        """
        mocker.patch(
            'app.models.dataset.KubernetesClient',
            return_value=Mock(
                read_namespaced_secret=Mock(
                    return_value=Mock(data={"krb5.conf": ""})
                )
            )
        )
        data_body = dataset_kerberos_post_body.copy()
        self.post_dataset(client, post_json_admin_header, data_body, code=400)

        self.assert_datasets_by_name(data_body['name'], 0)

    @mock.patch('app.datasets_api.Dataset.add')
    def test_post_dataset_kerberos_missing_required_field(
            self,
            ds_add_mock,
            post_json_admin_header,
            client,
            k8s_config,
            dataset_kerberos_post_body,
            mocker
        ):
        """
        /datasets POST is not successful if the request is missing the username field
        """
        dataset_kerberos_post_body.pop("username")
        self.post_dataset(client, post_json_admin_header, dataset_kerberos_post_body, code=400)

        self.assert_datasets_by_name(dataset_kerberos_post_body['name'], 0)


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
