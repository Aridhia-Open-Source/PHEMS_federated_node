from kubernetes.client.exceptions import ApiException
from unittest import mock
from unittest.mock import Mock

from app.helpers.exceptions import KeycloakError
from app.models.dataset import Dataset
from app.helpers.exceptions import KeycloakError
from tests.datasets.datasets_mixin import MixinTestDataset


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
            user_uuid,
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
        mock_kc_patch_api.return_value.get_user_by_id.return_value = {"email": dar_user}

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

    @mock.patch('app.datasets_api.Dataset.add')
    def test_patch_dataset_kerberos_missing_fields(
            self,
            ds_add_mock,
            post_json_admin_header,
            client,
            k8s_config,
            dataset_post_body,
            mocker
        ):
        """
        /datasets PATCH is not successful if the cm provided is missing
        required keys
        """
        mocker.patch(
            'app.models.dataset.KubernetesClient',
            return_value=Mock(
                read_namespaced_config_map=Mock(
                    return_value=Mock(data={"krb5.conf": ""})
                )
            )
        )
        data_body = dataset_post_body.copy()
        data_body['name'] = 'TestDs78'
        self.post_dataset(client, post_json_admin_header, data_body, code=400)

        self.assert_datasets_by_name(data_body['name'], 0)
