import json
from kubernetes.client.exceptions import ApiException
import re
from unittest import mock
from unittest.mock import Mock

from kubernetes.client.exceptions import ApiException

from app.helpers.const import TASK_POD_RESULTS_PATH
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


class TestPostTask:
    def test_create_task(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            task_body,
            v1_crd_mock
        ):
        """
        Tests task creation returns 201
        """
        response = client.post(
            '/tasks/',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]
        # Make sure the two init containers are created
        assert len(pod_body.spec.init_containers) == 2
        assert [pod.name for pod in pod_body.spec.init_containers] == [f"init-{response.json["task_id"]}", "fetch-data"]

    def test_create_task_no_db_query(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns 201, if the db_query field
        is not provided, the connection string is passed
        as env var instead of QUERY, FROM_DIALECT and TO_DIALECT.
        Also checks that only one init container is created for the
        folder creation in the PV
        """
        task_body.pop("db_query")
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]
        # The fetch_data init container should not be created
        assert len(pod_body.spec.init_containers) == 1
        assert pod_body.spec.init_containers[0].name == "init-1"
        envs = [env.name for env in pod_body.spec.containers[0].env]
        assert "CONNECTION_STRING" in envs
        assert set(envs).intersection({"QUERY", "FROM_DIALECT", "TO_DIALECT"}) == set()

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

    def test_create_task_image_same_name_different_registry(
            self,
            k8s_client,
            cr_client,
            registry_client,
            post_json_admin_header,
            client,
            container,
            task_body
        ):
        """
        Tests task creation is successful if two images are mapped with the
        same name, but different registry
        """
        registry = Registry(url="another.azureacr.io", username="user", password="pass")
        registry.add()
        Container(registry=registry, name=container.name, tag=container.tag).add()
        response = client.post(
            '/tasks/',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201

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

    def test_create_task_controller_not_deployed_no_crd(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            k8s_client,
            task_body,
            v1_crd_mock
        ):
        """
        Tests task creation returns 201. It should not try to
        create a CRD if the task controller is not deployed
        """
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()

    def test_create_task_controller_deployed_create_crd(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            set_task_controller_env,
            k8s_client,
            task_body,
            v1_crd_mock
        ):
        """
        Tests task creation returns 201. It should try to
        create a CRD if the task controller is deployed
        """
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.create_cluster_custom_object.assert_called()

    def test_create_task_from_controller(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            k8s_client,
            v1_crd_mock,
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
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()

    def test_task_connection_string_postgres(
            self,
            task,
            cr_client,
            reg_k8s_client,
            registry_client,
    ):
        """
        Simple test to make sure the generated connection string
        follows the global format
        """
        task.db_query = None
        task.run()
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]
        env = [env.value for env in pod_body.spec.containers[0].env if env.name == "CONNECTION_STRING"][0]
        assert re.match(r'driver={PostgreSQL ANSI};Uid=.*;Pwd=.*;Server=.*;Database=.*;$', env) is not None

    def test_task_connection_string_oracle(
            self,
            task,
            cr_client,
            reg_k8s_client,
            registry_client,
            dataset_oracle
    ):
        """
        Simple test to make sure the generated connection string
        follows the specific format for OracleDB
        """
        task.db_query = None
        task.dataset = dataset_oracle
        task.run()
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]
        env = [env.value for env in pod_body.spec.containers[0].env if env.name == "CONNECTION_STRING"][0]
        assert re.match(r'driver={Oracle ODBC Driver};Uid=.*;PSW=.*;DBQ=.*;$', env) is not None


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
