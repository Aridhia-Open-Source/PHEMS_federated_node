import json

from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


class TestValidateTask:
    def test_validate_task(
            self,
            client,
            task_body,
            cr_client,
            registry_client,
            post_json_admin_header
        ):
        """
        Test the validation endpoint can be used by admins returns 201
        """
        response = client.post(
            '/tasks/validate',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 200

    def test_validate_task_admin_missing_dataset(
            self,
            client,
            task_body,
            cr_client,
            registry_client,
            post_json_admin_header
        ):
        """
        Test the validation endpoint can be used by admins returns
        an error message if the dataset info is not provided
        """
        task_body["tags"].pop("dataset_id")
        response = client.post(
            '/tasks/validate',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "Administrators need to provide `tags.dataset_id` or `tags.dataset_name`"

    def test_validate_task_basic_user(
            self,
            mocks_kc_tasks,
            mocker,
            client,
            task_body,
            cr_client,
            registry_client,
            post_json_user_header: dict[str, str],
            access_request,
            user_uuid,
            dar_user
        ):
        """
        Test the validation endpoint can be used by non-admins returns 201
        """
        mocks_kc_tasks["wrappers"].return_value.get_user_by_username.return_value = {"id": user_uuid}

        post_json_user_header["project-name"] = access_request.project_name
        response = client.post(
            '/tasks/validate',
            data=json.dumps(task_body),
            headers=post_json_user_header
        )
        assert response.status_code == 200, response.json

