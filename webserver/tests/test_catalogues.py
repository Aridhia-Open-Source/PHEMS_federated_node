from app.models.catalogue import Catalogue
from tests.test_datasets import MixinTestDataset


class TestCatalogues(MixinTestDataset):
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
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)
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
        self.post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{data_body['name']}/catalogue",
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.json.items() >= data_body["catalogue"].items()

    def test_edit_existing_catalogue(
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

        data_body = {"catalogue": dataset_post_body["catalogue"]}
        data_body["catalogue"]["description"] = "shiny new table"

        response = client.patch(
            f"/datasets/{resp_ds["dataset_id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        catalogue = Catalogue.query.filter(Catalogue.dataset_id == resp_ds["dataset_id"]).all()
        assert len(catalogue) == 1
        assert catalogue[0].description == "shiny new table"

    def test_add_catalogue_to_existing_dataset(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset
        ):
        """
        Tests that sending PUT /dataset creates a new Catalogue
        linked to the existing dataset
        """
        data_body = dataset_post_body.copy()
        data_body.pop("catalogue")
        data_body['name'] = 'TestDs78'
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)

        assert Catalogue.query.filter(Catalogue.dataset_id == resp_ds["dataset_id"]).count() == 0

        data_body = {
            "catalogue": {
                "title": "new_table",
                "description": "data dummy"
            }
        }
        response = client.patch(
            f"/datasets/{resp_ds["dataset_id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        assert Catalogue.query.filter(Catalogue.dataset_id == resp_ds["dataset_id"]).count() == 1

    def test_patch_catalogue_doesnt_add_new_one_if_exists(
            self,
            client,
            dataset_post_body,
            post_json_admin_header,
            dataset
        ):
        """
        Tests that sending PUT /dataset does not create a new
        Catalogue if it's the same as the existing one
        """
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)

        data_body = {
            "catalogue": data_body["catalogue"]
        }
        response = client.patch(
            f"/datasets/{resp_ds["dataset_id"]}",
            json=data_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        assert Catalogue.query.filter(Catalogue.dataset_id == resp_ds["dataset_id"]).count() == 1

    def test_get_catalogue_not_allowed_user(
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
            f"/datasets/{resp_ds["dataset_id"]}/catalogue",
            headers=simple_user_header
        )
        assert response.status_code == 403
