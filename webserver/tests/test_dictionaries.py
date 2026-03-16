from pytest import mark
from sqlalchemy import func, select

from app.models.dictionary import Dictionary
from tests.test_datasets import MixinTestDataset


class TestDictionaries(MixinTestDataset):
    """
    Collection of tests for dictionaries requests
    """
    @mark.asyncio
    async def test_admin_get_dictionaries(
            self,
            client,
            dataset,
            v1_ds_mock,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header,
            mock_kc_client_dataset_route
    ):
        """
        Check that admin can see the dictionaries for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)
        response = await client.get(
            f"/datasets/{resp_ds["id"]}/dictionaries",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        for i in range(0, len(data_body["dictionaries"])):
            assert response.json()[i].items() >= data_body["dictionaries"][i].items()

    @mark.asyncio
    async def test_add_invalid_dict_format_fails(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            v1_ds_mock,
            dataset,
            mock_kc_client_dataset_route
        ):
        """
        Tests that sending a POST /dataset fails if the dictionary is not
        a list of dict
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        data_body["dictionaries"] = dataset_post_body["dictionaries"][0]["description"]

        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body, 400)

        assert resp_ds["error"][0]["message"] == "Input should be a valid list"
        assert await self.run_query(
            select(func.count(Dictionary.id)),
            "one") == 0

    @mark.asyncio
    async def test_admin_get_dictionaries_dataset_name(
            self,
            client,
            dataset,
            v1_ds_mock,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header,
            mock_kc_client_dataset_route
    ):
        """
        Check that admin can see the dictionaries for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        await self.post_dataset(client, post_json_admin_header, data_body)
        response = await client.get(
            f"/datasets/{data_body['name']}/dictionaries",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        for i in range(0, len(data_body["dictionaries"])):
            assert response.json()[i].items() >= data_body["dictionaries"][i].items()

    @mark.asyncio
    async def test_edit_existing_dictionary(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset,
            v1_ds_mock,
            mock_kc_client_dataset_route
        ):
        """
        Tests that sending PUT /dataset updates the dictionaries
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {"dictionaries": dataset_post_body["dictionaries"]}
        data_body["dictionaries"][0]["description"] = "shiny new table"

        response = await client.patch(
            f"/datasets/{resp_ds["id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        dictionaries = await self.run_query(
            select(Dictionary).filter_by(dataset_id=resp_ds["id"], description="shiny new table")
        )

        for dictionary in dictionaries:
            for k, v in data_body["dictionaries"][0].items():
                assert getattr(dictionary, k) == v

    @mark.asyncio
    async def test_add_dictionary_to_existing_dataset(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            v1_ds_mock,
            dataset,
            mock_kc_client_dataset_route
        ):
        """
        Tests that sending PUT /dataset creates a new dictionary
        linked to the existing dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {
            "dictionaries": [{
                "table_name": "new_table",
                "field_name": "data",
                "description": "data dummy"
            }]
        }
        response = await client.patch(
            f"/datasets/{resp_ds["id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        assert await self.run_query(
            select(func.count(Dictionary.id)).where(Dictionary.dataset_id == resp_ds["id"]),
            "one") == 2

    @mark.asyncio
    async def test_patch_dictionary_fails_if_exists(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            v1_ds_mock,
            dataset,
            mock_kc_client_dataset_route
        ):
        """
        Tests that sending PUT /dataset does not create a new
        dictionary if it's the same as the existing one
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {
            "dictionaries": data_body["dictionaries"]
        }
        response = await client.patch(
            f"/datasets/{resp_ds["id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        assert await self.run_query(
            select(func.count(Dictionary.id)).filter_by(dataset_id=resp_ds["id"]),
            "one") == 1

    @mark.asyncio
    async def test_patch_dictionary_fails_if_mandatory_field_missing(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            v1_ds_mock,
            dataset,
            mock_kc_client_dataset_route
        ):
        """
        Tests that sending PUT /dataset does not create a new
        dictionary if it's the same as the existing one
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {
            "dictionaries": data_body["dictionaries"]
        }
        data_body["dictionaries"][0].pop("field_name")

        response = await client.patch(
            f"/datasets/{resp_ds["id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json()["error"][0]["message"] == "Field required"
        assert "field_name" in response.json()["error"][0]["field"]

    @mark.asyncio
    async def test_get_dictionaries_not_allowed_user(
            self,
            client,
            dataset,
            v1_ds_mock,
            dataset_post_body,
            post_json_admin_header,
            simple_user_header,
            mock_kc_client_dataset_route,
            base_kc_mock_args
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the dictionaries for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        base_kc_mock_args.is_token_valid.return_value = False
        response = await client.get(
            f"/datasets/{resp_ds["id"]}/dictionaries",
            headers=simple_user_header
        )
        assert response.status_code == 403


class TestDictionaryTable(MixinTestDataset):
    """
    Collection of tests for dictionaries/table requests
    """
    @mark.asyncio
    async def test_admin_get_dictionary_table(
            self,
            client,
            dataset,
            v1_ds_mock,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header,
            mock_kc_client_dataset_route
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)
        response = await client.get(
            f"/datasets/{resp_ds["id"]}/dictionaries/test",
            headers=simple_admin_header
        )
        assert response.status_code == 200

    @mark.asyncio
    async def test_admin_get_dictionary_table_dataset_name(
            self,
            client,
            dataset,
            v1_ds_mock,
            simple_admin_header,
            post_json_admin_header,
            dataset_post_body,
            mock_kc_client_dataset_route
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        await self.post_dataset(client, post_json_admin_header, data_body)
        response = await client.get(
            f"/datasets/{data_body['name']}/dictionaries/test",
            headers=simple_admin_header
        )
        assert response.status_code == 200

    @mark.asyncio
    async def test_admin_get_dictionary_table_dataset_not_found(
            self,
            client,
            dataset,
            v1_ds_mock,
            simple_admin_header,
            mock_kc_client_dataset_route
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

    @mark.asyncio
    async def test_unauth_user_get_dictionary_table(
            self,
            client,
            dataset,
            v1_ds_mock,
            dataset_post_body,
            post_json_admin_header,
            simple_user_header,
            base_kc_mock_args,
            mock_kc_client_dataset_route
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        base_kc_mock_args.is_token_valid.return_value = False
        response = await client.get(
            f"/datasets/{resp_ds["id"]}/dictionaries/test",
            headers=simple_user_header
        )
        assert response.status_code == 403
