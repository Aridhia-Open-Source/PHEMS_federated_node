import json
import pytest
from copy import deepcopy
from unittest import mock
from datetime import datetime, timedelta
from kubernetes.client.exceptions import ApiException
from unittest import mock
from unittest.mock import Mock

from app.helpers.const import CLEANUP_AFTER_DAYS, TASK_POD_RESULTS_PATH
from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.models.task import Task
from tests.fixtures.azure_cr_fixtures import *


@pytest.fixture(scope='function')
def task_body(dataset, container):
    return deepcopy({
        "name": "Test Task",
        "requested_by": "das9908-as098080c-9a80s9",
        "executors": [
            {
                "image": container.full_image_name(),
                "command": ["R", "-e", "df <- as.data.frame(installed.packages())[,c('Package', 'Version')];write.csv(df, file='/mnt/data/packages.csv', row.names=FALSE);Sys.sleep(10000)\""],
                "env": {
                    "VARIABLE_UNIQUE": 123,
                    "USERNAME": "test"
                }
            }
        ],
        "db_query": {
            "query": "SELECT * FROM table",
            "dialect": "postgres"
        },
        "description": "First task ever!",
        "tags": {
            "dataset_id": dataset.id,
            "test_tag": "some content"
        },
        "inputs": {},
        "outputs": {},
        "resources": {},
        "volumes": {}
    })

@pytest.fixture
def running_state():
    return Mock(
        state=Mock(
            running=Mock(
                started_at="1/1/2024"
            ),
            waiting=None,
            terminated=None
        )
    )

@pytest.fixture
def waiting_state():
    return Mock(
        state=Mock(
            waiting=Mock(
                started_at="1/1/2024"
            ),
            running=None,
            terminated=None
        )
    )

@pytest.fixture
def terminated_state():
    return Mock(
        state=Mock(
            terminated=Mock(
                started_at="1/1/2024",
                finished_at="1/1/2024",
                reason="Completed successfully!",
                exit_code=0,
            ),
            running=None,
            waiting=None
        )
    )

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


class TestPostTask:
    def test_create_task(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 201
        """
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201

    def test_create_task_invalid_output_field(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 4xx request when output
        is not a dictionary
        """
        task_body["outputs"] = []
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json == {"error": "\"outputs\" filed muct be a json object or dictionary"}

    def test_create_task_no_output_field_reverts_to_default(
            self,
            cr_client,
            reg_k8s_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 201 but the volume mounted
        is the default one
        """
        task_body.pop("outputs")
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]
        assert len(pod_body.spec.containers[0].volume_mounts) == 1
        assert pod_body.spec.containers[0].volume_mounts[0].mount_path == TASK_POD_RESULTS_PATH

    def test_create_task_with_ds_name(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            dataset,
            task_body
        ):
        """
        Tests task creation with a dataset name returns 201
        """
        data = task_body
        data["tags"].pop("dataset_id")
        data["tags"]["dataset_name"] = dataset.name

        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 201

    def test_create_task_with_ds_name_and_id(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            dataset,
            task_body
        ):
        """
        Tests task creation with a dataset name and id returns 201
        """
        data = task_body
        data["tags"]["dataset_name"] = dataset.name

        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 201

    def test_create_task_with_conflicting_ds_name_and_id(
            self,
            cr_client,
            post_json_admin_header,
            client,
            dataset,
            task_body
        ):
        """
        Tests task creation with a dataset name that does not exists
        and a valid id returns 201
        """
        data = task_body
        data["tags"]["dataset_name"] = "something else"

        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json["error"] == f"Dataset \"something else\" with id {dataset.id} does not exist"

    def test_create_task_with_non_existing_dataset(
            self,
            cr_client,
            post_json_admin_header,
            client,
            task_body
        ):
        """
        Tests task creation returns 404 when the requested dataset doesn't exist
        """
        data = task_body
        data["dataset_id"] = '123456'

        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json == {"error": "Dataset 123456 does not exist"}

    def test_create_task_with_non_existing_dataset_name(
            self,
            cr_client,
            post_json_admin_header,
            client,
            dataset,
            task_body
        ):
        """
        Tests task creation returns 404 when the
        requested dataset name doesn't exist
        """
        data = task_body
        data["tags"].pop("dataset_id")
        data["tags"]["dataset_name"] = "something else"

        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json == {"error": "Dataset something else does not exist"}

    @mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
    def test_create_unauthorized_task(
            self,
            kc_valid_mock,
            cr_client,
            post_json_user_header,
            dataset,
            client,
            task_body
        ):
        """
        Tests task creation returns 403 if a user is not authorized to
        access the dataset
        """
        data = task_body
        data["dataset_id"] = dataset.id

        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_user_header
        )
        assert response.status_code == 403

    def test_create_task_image_not_found(
            self,
            cr_client_404,
            post_json_admin_header,
            client,
            task_body
        ):
        """
        Tests task creation returns 500 with a requested docker image is not found
        """
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        assert response.json == {"error": f"Image {task_body["executors"][0]["image"]} not found on our repository"}

    def test_create_task_inputs_not_default(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            reg_k8s_client,
            task_body
        ):
        """
        Tests task creation returns 201 and if users provide
        custom location for inputs, this is set as volumeMount
        """
        task_body["inputs"] = {"file.csv": "/data/in"}
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]

        assert len(pod_body.spec.containers[0].volume_mounts) == 2
        # Check if the mount volume is on the correct path
        assert "/data/in" in [vm.mount_path for vm in pod_body.spec.containers[0].volume_mounts]
        # Check if the INPUT_PATH variable is set
        assert ["/data/in/file.csv"] == [ev.value for ev in pod_body.spec.containers[0].env if ev.name == "INPUT_PATH"]

    def test_create_task_input_path_env_var_override(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            reg_k8s_client,
            task_body
        ):
        """
        Tests task creation returns 201 and if users provide
        INPUT_PATH as a env var, use theirs
        """
        task_body["executors"][0]["env"] = {"INPUT_PATH": "/data/in/file.csv"}
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]

        # Check if the INPUT_PATH variable is set
        assert ["/data/in/file.csv"] == [ev.value for ev in pod_body.spec.containers[0].env if ev.name == "INPUT_PATH"]

    def test_create_task_invalid_output_field(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 4xx request when output
        is not a dictionary
        """
        task_body["outputs"] = []
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json == {"error": "\"outputs\" field must be a json object or dictionary"}

    def test_create_task_invalid_inputs_field(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 4xx request when inputs
        is not a dictionary
        """
        task_body["inputs"] = []
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json == {"error": "\"inputs\" field must be a json object or dictionary"}

    def test_create_task_no_output_field_reverts_to_default(
            self,
            cr_client,
            reg_k8s_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 201 but the resutls volume mounted
        is the default one
        """
        task_body.pop("outputs")
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]
        assert len(pod_body.spec.containers[0].volume_mounts) == 2
        assert TASK_POD_RESULTS_PATH in [vm.mount_path for vm in pod_body.spec.containers[0].volume_mounts]

    def test_create_task_no_inputs_field_reverts_to_default(
            self,
            cr_client,
            reg_k8s_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 201 but the volume mounted
        is the default one for the inputs
        """
        task_body.pop("inputs")
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]
        assert len(pod_body.spec.containers[0].volume_mounts) == 2
        assert [vm.mount_path for vm in pod_body.spec.containers[0].volume_mounts] == ["/mnt/inputs", TASK_POD_RESULTS_PATH]

    def test_create_task_from_controller(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 201. Should be consistent
        with or without the task_controller flag
        """
        task_body["task_controller"] = True
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201


class TestCancelTask:
    def test_cancel_task(
            self,
            client,
            simple_admin_header,
            task
        ):
        """
        Test that an admin can cancel an existing task
        """
        response = client.post(
            f'/tasks/{task.id}/cancel',
            headers=simple_admin_header
        )
        assert response.status_code == 201

    def test_cancel_404_task(
            self,
            client,
            simple_admin_header
        ):
        """
        Test that an admin can cancel a non-existing task returns a 404
        """
        response = client.post(
            '/tasks/123456/cancel',
            headers=simple_admin_header
        )
        assert response.status_code == 404


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


class TestTaskResults:
    def test_get_results(
        self,
        cr_client,
        registry_client,
        post_json_admin_header,
        simple_admin_header,
        client,
        task_body,
        mocker,
        reg_k8s_client,
        task
    ):
        """
        A simple test with mocked PVs to test a successful result
        fetch
        """
        # The mock has to be done manually rather than use the fixture
        # as it complains about the return value of the list_pod method
        mocker.patch('app.models.task.uuid4', return_value="1dc6c6d1-417f-409a-8f85-cb9d20f7c741")

        pod_mock = Mock()
        pod_mock.metadata.labels = {"job-name": "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"}
        pod_mock.metadata.name = "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"
        pod_mock.spec.containers = [Mock(image=task.docker_image)]
        pod_mock.status.container_statuses = [Mock(ready=True)]
        reg_k8s_client["list_namespaced_pod_mock"].return_value.items = [pod_mock]

        mocker.patch(
            'app.models.task.Task.get_status',
            return_value={"running": {}}
        )

        response = client.get(
            f'/tasks/{task.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.content_type == "application/x-tar"

    def test_get_results_job_creation_failure(
        self,
        simple_admin_header,
        client,
        reg_k8s_client,
        task
    ):
        """
        Tests that the job creation to fetch results from a PV returns a 500
        error code
        """
        # Get results - creating a job fails
        reg_k8s_client["create_namespaced_job_mock"].side_effect = ApiException(status=500, reason="Something went wrong")

        pod_mock = Mock()
        pod_mock.metadata.labels = {"job-name": "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"}
        pod_mock.metadata.name = "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"
        pod_mock.spec.containers = [Mock(image=task.docker_image)]
        pod_mock.status.container_statuses = [Mock(ready=True)]
        reg_k8s_client["list_namespaced_pod_mock"].return_value.items = [pod_mock]

        response = client.get(
            f'/tasks/{task.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == 'Failed to run pod: Something went wrong'

    def test_results_not_found_with_expired_date(
        self,
        simple_admin_header,
        client,
        task
    ):
        """
        A task result are being deleted after a declared number of days.
        This test makes sure an error is returned as expected
        """
        task.created_at=datetime.now() - timedelta(days=CLEANUP_AFTER_DAYS)
        response = client.get(
            f'/tasks/{task.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 500
        assert response.json["error"] == 'Tasks results are not available anymore. Please, run the task again'


class TestResourceValidators:
    def test_valid_values(
            self,
            mocker,
            mocks_kc_tasks,
            user_uuid,
            registry_client,
            cr_client,
            task_body
        ):
        """
        Tests that the expected resource values are accepted
        """
        task_body["resources"] = {
            "limits": {
                "cpu": "100m",
                "memory": "100Mi"
            },
            "requests": {
                "cpu": "0.1",
                "memory": "100Mi"
            }
        }
        Task.validate(task_body)

    def test_invalid_memory_values(
            self,
            mocker,
            mocks_kc_tasks,
            user_uuid,
            cr_client,
            registry_client,
            task_body
        ):
        """
        Tests that the unexpected memory values are not accepted
        """
        invalid_values = ["hundredMi", "100ki", "100mi", "0.1Ki", "Mi100"]
        for in_val in invalid_values:
            task_body["resources"] = {
                "limits": {
                    "cpu": "100m",
                    "memory": "100Mi"
                },
                "requests": {
                    "cpu": "0.1",
                    "memory": in_val
                }
            }
            with pytest.raises(InvalidRequest) as ir:
                Task.validate(task_body)
            assert ir.value.description == f'Memory resource value {in_val} not valid.'

    def test_invalid_cpu_values(
            self,
            mocker,
            mocks_kc_tasks,
            user_uuid,
            cr_client,
            registry_client,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        invalid_values = ["5.24.1", "hundredm", "100Ki", "100mi", "0.1m"]

        for in_val in invalid_values:
            task_body["resources"] = {
                "limits": {
                    "cpu": in_val,
                    "memory": "100Mi"
                },
                "requests": {
                    "cpu": "0.1",
                    "memory": "100Mi"
                }
            }
            with pytest.raises(InvalidRequest) as ir:
                Task.validate(task_body)
            assert ir.value.description == f'Cpu resource value {in_val} not valid.'

    def test_mem_limit_lower_than_request_fails(
            self,
            mocker,
            mocks_kc_tasks,
            user_uuid,
            cr_client,
            registry_client,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        task_body["resources"] = {
            "limits": {
                "cpu": "100m",
                "memory": "100Mi"
            },
            "requests": {
                "cpu": "0.1",
                "memory": "200000Ki"
            }
        }
        with pytest.raises(InvalidRequest) as ir:
            Task.validate(task_body)
        assert ir.value.description == 'Memory limit cannot be lower than request'

    def test_cpu_limit_lower_than_request_fails(
            self,
            mocker,
            mocks_kc_tasks,
            user_uuid,
            cr_client,
            registry_client,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        task_body["resources"] = {
            "limits": {
                "cpu": "100m",
                "memory": "100Mi"
            },
            "requests": {
                "cpu": "0.2",
                "memory": "100Mi"
            }
        }
        with pytest.raises(InvalidRequest) as ir:
            Task.validate(task_body)
        assert ir.value.description == 'Cpu limit cannot be lower than request'
