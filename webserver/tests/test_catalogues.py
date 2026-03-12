from pytest import mark
from sqlalchemy import func, select

from app.models.catalogue import Catalogue
from tests.test_datasets import MixinTestDataset


class TestCatalogues(MixinTestDataset):
    """
    Collection of tests for catalogues requests
    """
    @mark.asyncio
    async def test_admin_get_catalogue(
            self,
            client,
            dataset,
            v1_ds_mock,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header
    ):
        """
        Check that admin can see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)
        response = await client.get(
            f"/datasets/{resp_ds["id"]}/catalogue",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.json().items() >= data_body["catalogue"].items()

    @mark.asyncio
    async def test_admin_get_catalogue_dataset_name(
            self,
            client,
            dataset,
            v1_ds_mock,
            dataset_post_body,
            post_json_admin_header,
            simple_admin_header,
    ):
        """
        Check that admin can see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        await self.post_dataset(client, post_json_admin_header, data_body)
        response = await client.get(
            f"/datasets/{data_body['name']}/catalogue",
            headers=simple_admin_header
        )
        assert response.status_code == 200, response.json()
        assert response.json().items() >= data_body["catalogue"].items()

    @mark.asyncio
    async def test_edit_existing_catalogue(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset,
            v1_ds_mock,
        ):
        """
        Tests that sending PUT /dataset updates the dictionaries
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {"catalogue": dataset_post_body["catalogue"]}
        data_body["catalogue"]["description"] = "shiny new table"

        response = await client.patch(
            f"/datasets/{resp_ds["id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        catalogue = await self.run_query(select(Catalogue).where(Catalogue.dataset_id == resp_ds["id"]), "all")
        assert len(catalogue) == 1
        assert catalogue[0].description == "shiny new table"

    @mark.asyncio
    async def test_add_catalogue_to_existing_dataset(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset,
            v1_ds_mock,
        ):
        """
        Tests that sending PUT /dataset creates a new Catalogue
        linked to the existing dataset
        """
        data_body = dataset_post_body.copy()
        data_body.pop("catalogue")
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        assert await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.dataset_id == resp_ds["id"]), "one") == 0

        data_body = {
            "catalogue": {
                "title": "new_table",
                "version": "2a",
                "description": "data dummy"
            }
        }
        response = await client.patch(
            f"/datasets/{resp_ds["id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        assert await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.dataset_id == resp_ds["id"]), "one") == 1

    @mark.asyncio
    async def test_patch_catalogue_doesnt_add_new_one_if_exists(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset,
            v1_ds_mock,
        ):
        """
        Tests that sending PUT /dataset does not create a new
        Catalogue if it's the same as the existing one
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {
            "catalogue": data_body["catalogue"]
        }
        response = await client.patch(
            f"/datasets/{resp_ds["id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        assert await self.run_query(select(func.count(Catalogue.id)).where(Catalogue.dataset_id == resp_ds["id"]), "one") == 1

    @mark.asyncio
    async def test_get_catalogue_not_allowed_user(
            self,
            client,
            dataset,
            v1_ds_mock,
            dataset_post_body,
            post_json_admin_header,
            simple_user_header,
            mocker,
            mock_kc_client
    ):
        """
        Check that non-admin or non DAR approved users
        cannot see the catalogue for a given dataset
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = await self.post_dataset(client, post_json_admin_header, data_body)

        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

        response = await client.get(
            f"/datasets/{resp_ds["id"]}/catalogue",
            headers=simple_user_header
        )
        assert response.status_code == 403
