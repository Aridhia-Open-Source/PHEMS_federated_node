from app.models.dictionary import Dictionary
from tests.test_datasets import MixinTestDataset


class TestDictionaries(MixinTestDataset):
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
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/dictionaries",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        for i in range(0, len(data_body["dictionaries"])):
            assert response.json[i].items() >= data_body["dictionaries"][i].items()

    def test_add_invalid_dict_format_fails(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset
        ):
        """
        Tests that sending a POST /dataset fails if the dictionary is not
        a list of dict
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        data_body["dictionaries"] = dataset_post_body["dictionaries"][0]["description"]

        resp_ds = self.post_dataset(client, post_json_admin_header, data_body, 400)

        assert resp_ds["error"] == "dictionaries should be a list."
        assert Dictionary.query.count() == 0

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
        self.post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{data_body['name']}/dictionaries",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        for i in range(0, len(data_body["dictionaries"])):
            assert response.json[i].items() >= data_body["dictionaries"][i].items()

    def test_edit_existing_dictionary(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset
        ):
        """
        Tests that sending PUT /dataset updates the dictionaries
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {"dictionaries": dataset_post_body["dictionaries"]}
        data_body["dictionaries"][0]["description"] = "shiny new table"

        response = client.patch(
            f"/datasets/{resp_ds["dataset_id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        dictionaries = Dictionary.query.filter(Dictionary.dataset_id == resp_ds["dataset_id"]).all()
        for dictionary in dictionaries:
            for k, v in data_body["dictionaries"][0].items():
                assert getattr(dictionary, k) == v

    def test_add_dictionary_to_existing_dataset(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset
        ):
        """
        Tests that sending PUT /dataset creates a new dictionary
        linked to the existing dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {
            "dictionaries": [{
                "table_name": "new_table",
                "field_name": "data",
                "description": "data dummy"
            }]
        }
        response = client.patch(
            f"/datasets/{resp_ds["dataset_id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        assert Dictionary.query.filter(Dictionary.dataset_id == resp_ds["dataset_id"]).count() == 2

    def test_patch_dictionary_fails_if_exists(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset
        ):
        """
        Tests that sending PUT /dataset does not create a new
        dictionary if it's the same as the existing one
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {
            "dictionaries": data_body["dictionaries"]
        }
        response = client.patch(
            f"/datasets/{resp_ds["dataset_id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        assert Dictionary.query.filter(Dictionary.dataset_id == resp_ds["dataset_id"]).count() == 1

    def test_patch_dictionary_fails_if_mandatory_field_missing(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset
        ):
        """
        Tests that sending PUT /dataset does not create a new
        dictionary if it's the same as the existing one
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {
            "dictionaries": data_body["dictionaries"]
        }
        data_body["dictionaries"][0].pop("field_name")

        response = client.patch(
            f"/datasets/{resp_ds["dataset_id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "Field \"field_name\" missing"

    def test_get_dictionaries_not_allowed_user(
            self,
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_user_header,
            mocker
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the dictionaries for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)

        mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/dictionaries",
            headers=simple_user_header
        )
        assert response.status_code == 403


class TestDictionaryTable(MixinTestDataset):
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
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/dictionaries/test",
            headers=simple_admin_header
        )
        assert response.status_code == 200

    def test_admin_get_dictionary_table_dataset_name(
            self,
            client,
            dataset,
            simple_admin_header,
            post_json_admin_header,
            dataset_post_body
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        self.post_dataset(client, post_json_admin_header, data_body)
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
            client,
            dataset,
            dataset_post_body,
            post_json_admin_header,
            simple_user_header,
            mocker
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)

        mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/dictionaries/test",
            headers=simple_user_header
        )
        assert response.status_code == 403
