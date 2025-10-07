from unittest.mock import patch
from kubernetes.client.exceptions import ApiException

from app.models.dataset import Dataset
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from tests.datasets.datasets_mixin import MixinTestDataset


class TestDeleteDataset(MixinTestDataset):
    def test_delete_dataset_with_secrets(
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
        response = client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        k8s_client["delete_namespaced_secret_mock"].assert_called_with(
            secret_name, 'default'
        )

    def test_delete_dataset_not_found(
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
        response = client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        k8s_client["delete_namespaced_secret_mock"].assert_not_called()

    def test_delete_dataset_with_secrets_error(
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

        response = client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert Dataset.query.filter_by(id=ds_id).one_or_none()

    def test_delete_dataset_with_secrets_not_found_error(
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

        response = client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        assert not Dataset.query.filter_by(id=ds_id).one_or_none()

    def test_delete_dataset_with_catalougues(
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
        response = client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_admin_header
        )
        assert response.status_code == 204
        assert Catalogue.query.filter_by(dataset_id=ds_id).count() == 0
        assert Dictionary.query.filter_by(dataset_id=ds_id).count() == 0

    @patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
    def test_delete_dataset_unauthorized(
            self,
            token_valid_mock,
            client,
            dataset,
            post_json_user_header
    ):
        """
        Tests that a non admin cannot delete a dataset
        """
        ds_id = dataset.id
        response = client.delete(
            f"/datasets/{ds_id}",
            headers=post_json_user_header
        )
        assert response.status_code == 403
