from unittest.mock import Mock

from app.helpers.base_model import db
from app.models.task import Task
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


class TestGetTasks:
    def test_get_list_tasks(
            self,
            client,
            simple_admin_header,

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
            mocker,
            simple_user_header,
            mock_kc_client
        ):
        """
        Tests that non-admin users cannot see the list of tasks
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

        response = client.get(
            '/tasks/',
            headers=simple_user_header
        )
        assert response.status_code == 403

    def test_get_task_by_id_admin(
            self,
            mock_kc_client,
            cr_client,
            post_json_user_header,
            simple_admin_header,
            client,
            registry_client,
            k8s_client,
            task_body
        ):
        """
        If an admin wants to check a specific task they should be allowed regardless
        of who requested it
        """
        mock_kc_client["tasks_api_kc"].return_value.get_user_by_id.return_value = {"username": "user"}
        resp = client.post(
            '/tasks/',
            json=task_body,
            headers=post_json_user_header
        )
        assert resp.status_code == 201
        task_id = resp.json["task_id"]

        resp = client.get(
            f'/tasks/{task_id}',
            headers=simple_admin_header
        )
        assert resp.status_code == 200

    def test_get_task_by_id_non_admin_owner(
            self,
            simple_user_header,
            client,
            basic_user,
            task,
            mock_kc_client
        ):
        """
        If a user wants to check a specific task they should be allowed if they did request it
        """
        decode_return = {"sub": basic_user["id"]}
        decode_return.update(basic_user)
        mock_kc_client["tasks_api_kc"].return_value.decode_token.return_value = decode_return
        task.requested_by = basic_user["id"]
        resp = client.get(
            f'/tasks/{task.id}',
            headers=simple_user_header
        )
        assert resp.status_code == 200, resp.json

    def test_get_task_by_id_non_admin_non_owner(
            self,
            simple_user_header,
            client,
            task,
            mock_kc_client
        ):
        """
        If a user wants to check a specific task they should not be allowed if they did not request it
        """
        task_obj = db.session.get(Task, task.id)
        task_obj.requested_by = "some random uuid"
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

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
            json=task_body,
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
            json=task_body,
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
            json=task_body,
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

