from unittest.mock import Mock

from kubernetes.client.exceptions import ApiException

from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


class TestTasksLogs:
    def test_task_get_logs(
            self,
            post_json_admin_header,
            client,
            mocker,
            terminated_state,
            task
        ):
        """
        Basic test that will allow us to return
        the pods logs
        """
        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=Mock(
                status=Mock(
                    container_statuses=[terminated_state]
                )
            )
        )
        response_logs = client.get(
            f'/tasks/{task.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 200
        assert response_logs.json["logs"] == [
            'Example logs',
            'another line'
        ]

    def test_task_logs_non_existent(
            self,
            post_json_admin_header,
            client,
            task
        ):
        """
        Basic test that will check the appropriate error
        is returned when the task id does not exist
        """
        response_logs = client.get(
            f'/tasks/{task.id + 1}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 404
        assert response_logs.json["error"] == f"Task with id {task.id + 1} does not exist"

    def test_task_waiting_get_logs(
            self,
            post_json_admin_header,
            client,
            mocker,
            waiting_state,
            task
        ):
        """
        Basic test that will try to get logs for a pod
        in an init state.
        """
        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=Mock(
                status=Mock(
                    container_statuses=[waiting_state]
                )
            )
        )
        response_logs = client.get(
            f'/tasks/{task.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 200
        assert response_logs.json["logs"] == 'Task queued'

    def test_task_not_found_get_logs(
            self,
            post_json_admin_header,
            client,
            mocker,
            task
        ):
        """
        Basic test that will try to get the logs from a missing
        pod. This can happen if the task gets cleaned up
        """
        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=None
        )
        response_logs = client.get(
            f'/tasks/{task.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 400
        assert response_logs.json["error"] == f'Task pod {task.id} not found'

    def test_task_get_logs_fails(
            self,
            post_json_admin_header,
            client,
            k8s_client,
            mocker,
            task,
            terminated_state
        ):
        """
        Basic test that will try to get the logs, but k8s
        will raise an ApiException. It is expected a 500 status code
        """
        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=Mock(
                status=Mock(
                    container_statuses=[terminated_state]
                )
            )
        )
        k8s_client["read_namespaced_pod_log"].side_effect = ApiException()
        response_logs = client.get(
            f'/tasks/{task.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 500
        assert response_logs.json["error"] == 'Failed to fetch the logs'
