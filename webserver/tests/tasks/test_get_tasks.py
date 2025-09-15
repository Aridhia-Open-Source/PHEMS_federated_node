import json
from unittest import mock
from unittest.mock import Mock

from app.helpers.base_model import db
from app.models.task import Task
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


class TestGetTasks:
    def test_get_list_tasks(
            self,
            client,
            simple_admin_header
        ):
        """
        Tests that admin users can see the list of tasks
        """
        response = client.get(
            '/tasks/',
            headers=simple_admin_header
        )
        assert response.status_code == 200

    def test_get_list_tasks_base_user(
            self,
            client,
            simple_user_header
        ):
        """
        Tests that non-admin users cannot see the list of tasks
        """
        response = client.get(
            '/tasks/',
            headers=simple_user_header
        )
        assert response.status_code == 403

    def test_get_task_by_id_admin(
            self,
            mocks_kc_tasks,
            cr_client,
            post_json_admin_header,
            post_json_user_header,
            simple_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        If an admin wants to check a specific task they should be allowed regardless
        of who requested it
        """
        mocks_kc_tasks["tasks"].return_value.get_user_by_id.return_value = {"username": "user"}
        resp = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_user_header
        )
        assert resp.status_code == 201
        task_id = resp.json["task_id"]

        resp = client.get(
            f'/tasks/{task_id}',
            headers=simple_admin_header
        )
        assert resp.status_code == 200

    @mock.patch('app.helpers.keycloak.Keycloak.is_user_admin', return_value=False)
    @mock.patch('app.tasks_api.Keycloak.decode_token')
    def test_get_task_by_id_non_admin_owner(
            self,
            mocks_decode,
            mock_is_admin,
            mocks_kc_tasks,
            simple_user_header,
            client,
            basic_user,
            task,
            user_uuid
        ):
        """
        If a user wants to check a specific task they should be allowed if they did request it
        """
        mocks_decode.return_value = {"sub": basic_user["id"]}
        task.requested_by = basic_user["id"]
        resp = client.get(
            f'/tasks/{task.id}',
            headers=simple_user_header
        )
        assert resp.status_code == 200, resp.json

    @mock.patch('app.helpers.keycloak.Keycloak.is_user_admin', return_value=False)
    def test_get_task_by_id_non_admin_non_owner(
            self,
            mock_is_admin,
            mocks_kc_tasks,
            simple_user_header,
            client,
            task
        ):
        """
        If a user wants to check a specific task they should not be allowed if they did not request it
        """
        task_obj = db.session.get(Task, task.id)
        task_obj.requested_by = "some random uuid"

        resp = client.get(
            f'/tasks/{task.id}',
            headers=simple_user_header
        )
        assert resp.status_code == 403

    def test_get_task_status_running_and_waiting(
            self,
            cr_client,
            registry_client,
            running_state,
            waiting_state,
            post_json_admin_header,
            client,
            task_body,
            mocker,
            task
        ):
        """
        Test to verify the correct task status when it's
        waiting or Running on k8s. Output would be similar
        """
        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=Mock(
                status=Mock(
                    container_statuses=[running_state]
                )
            )
        )

        response_id = client.get(
            f'/tasks/{task.id}',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response_id.status_code == 200
        assert response_id.json["status"] == {'running': {'started_at': '1/1/2024'}}

        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=Mock(
                status=Mock(
                    container_statuses=[waiting_state]
                )
            )
        )

        response_id = client.get(
            f'/tasks/{task.id}',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response_id.status_code == 200
        assert response_id.json["status"] == {'waiting': {'started_at': '1/1/2024'}}

    def test_get_task_status_terminated(
            self,
            terminated_state,
            post_json_admin_header,
            client,
            task_body,
            mocker,
            task
        ):
        """
        Test to verify the correct task status when it's terminated on k8s
        """
        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=Mock(
                status=Mock(
                    container_statuses=[terminated_state]
                )
            )
        )

        response_id = client.get(
            f'/tasks/{task.id}',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response_id.status_code == 200
        expected_status = {
            'terminated': {
                'started_at': '1/1/2024',
                'finished_at': '1/1/2024',
                'reason': 'Completed successfully!',
                'exit_code': 0
            }
        }
        assert response_id.json["status"] == expected_status
