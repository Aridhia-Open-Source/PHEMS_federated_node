
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

    def test_get_catalogue_not_allowed_user(
            self,
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
        resp_ds = self.post_dataset(client, post_json_admin_header, data_body)
        response = client.get(
            f"/datasets/{resp_ds["dataset_id"]}/catalogue",
            headers=simple_user_header
        )
        assert response.status_code == 403
