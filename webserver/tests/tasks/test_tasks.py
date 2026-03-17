from datetime import timedelta
import json
import re
from pytest import mark
from kubernetes_asyncio.client.exceptions import ApiException
from unittest import mock
from unittest.mock import Mock

from unittest.mock import Mock, patch

from app.helpers.settings import settings
from app.models.task import Task
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *
from tests.fixtures.common_registry_fixtures import *
from tests.base_test_class import BaseTest


class TestGetTasks(BaseTest):
    @mark.asyncio
    async def test_get_list_tasks(
            self,
            client,
            simple_admin_header,
            mock_kc_client_task_model
        ):
        """
        Tests that admin users can see the list of tasks
        """
        response = await client.get(
            '/tasks',
            headers=simple_admin_header
        )
        assert response.status_code == 200

    @mark.asyncio
    async def test_get_list_tasks_base_user(
            self,
            client,
            simple_user_header,
            mock_kc_client_task_model,
            base_kc_mock_args
        ):
        """
        Tests that non-admin users cannot see the list of tasks
        """
        base_kc_mock_args.is_token_valid.return_value = False

        response = await client.get(
            '/tasks',
            headers=simple_user_header
        )
        assert response.status_code == 403

    @mark.asyncio
    async def test_get_task_by_id_admin(
            self,
            post_json_user_header,
            simple_admin_header,
            client,
            registry_client,
            v1_task_mock,
            task_body,
            mock_kc_client_task_model,
            base_kc_mock_args
        ):
        """
        If an admin wants to check a specific task they should be allowed regardless
        of who requested it
        """
        base_kc_mock_args.get_user_by_id.return_value = {"username": "user"}
        resp = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_user_header
        )
        assert resp.status_code == 201
        task_id = resp.json()["id"]

        resp = await client.get(
            f'/tasks/{task_id}',
            headers=simple_admin_header
        )
        assert resp.status_code == 200

    @mark.asyncio
    async def test_get_task_by_id_non_admin_owner(
            self,
            simple_user_header,
            client,
            basic_user,
            task,
            mock_kc_client_task_model,
            base_kc_mock_args
        ):
        """
        If a user wants to check a specific task they should be allowed if they did request it
        """
        decode_return = {"sub": basic_user["id"]}
        decode_return.update(basic_user)
        base_kc_mock_args.decode_token.return_value = decode_return

        t = await Task.get_by_id(self.db_session, task.id)
        t.requested_by = basic_user["id"]
        resp = await client.get(
            f'/tasks/{task.id}',
            headers=simple_user_header
        )
        assert resp.status_code == 200

    @mark.asyncio
    async def test_get_task_by_id_non_admin_non_owner(
            self,
            simple_user_header,
            client,
            task,
            mock_kc_client_task_model,
            base_kc_mock_args
        ):
        """
        If a user wants to check a specific task they should not be allowed if they did not request it
        """
        task_obj = await self.db_session.get(Task, task.id)
        task_obj.requested_by = "some random uuid"
        base_kc_mock_args.is_token_valid.return_value = False

        resp = await client.get(
            f'/tasks/{task.id}',
            headers=simple_user_header
        )
        assert resp.status_code == 403

    @mark.asyncio
    async def test_get_task_status_running_and_waiting(
            self,
            registry_client,
            running_state,
            waiting_state,
            simple_admin_header,
            client,
            task_body,
            mocker,
            task,
            mock_kc_client_task_model
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
        mocker.patch(
            'app.models.task.Task.get_expiration_date',
            return_value=datetime.now() + timedelta(days=1)
        )

        response_id = await client.get(
            f'/tasks/{task.id}',
            headers=simple_admin_header
        )
        assert response_id.status_code == 200, response_id.json()
        assert response_id.json()["status"] == {'running': {'started_at': '1/1/2024'}}

        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=Mock(
                status=Mock(
                    container_statuses=[waiting_state]
                )
            )
        )

        response_id = await client.get(
            f'/tasks/{task.id}',
            headers=simple_admin_header
        )
        assert response_id.status_code == 200, response_id.json()
        assert response_id.json()["status"] == {'waiting': {'started_at': '1/1/2024'}}

    @mark.asyncio
    async def test_get_task_status_terminated(
            self,
            terminated_state,
            post_json_admin_header,
            client,
            task_body,
            mocker,
            task,
            mock_kc_client_task_model
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

        response_id = await client.get(
            f'/tasks/{task.id}',
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
        assert response_id.json()["status"] == expected_status


class TestPostTask(BaseTest):
    @mark.asyncio
    async def test_create_task(
            self,
            post_json_admin_header,
            client,
            v1_task_mock,
            mock_args_k8s,
            registry_client,
            task_body,
            mock_kc_client_task_service,
            mock_args_crd,
            v1_crd_mock
        ):
        """
        Tests task creation returns 201
        """
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        mock_args_crd.api_client.create_cluster_custom_object.assert_not_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]
        # Make sure the two init containers are created
        assert len(pod_body.spec.init_containers) == 2
        assert [pod.name for pod in pod_body.spec.init_containers] == [f"init-{response.json()["id"]}", "fetch-data"]

    @mark.asyncio
    async def test_create_task_no_name_fails(
            self,
            post_json_admin_header,
            client,
            task_body,
            container,
            cr_name,
            registry,
            tags_request,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns an error when name is empty or null
        """
        for value in ["", " ", " " * 10]:
            task_body["name"] = value
            response = await client.post(
                '/tasks',
                json=task_body,
                headers=post_json_admin_header
            )
            assert response.status_code == 400
            assert response.json()["error"] == "name is a mandatory field"

    @mark.asyncio
    async def test_create_task_no_tag_fails(
            self,
            post_json_admin_header,
            client,
            task_body,
            container,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns an error when the image does not have a tag or sha
        """
        tagless_image = "".join(container.full_image_name().split(':')[:-1])
        task_body["executors"][0]["image"] = tagless_image
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json()["error"] == f"{tagless_image} does not have a tag. Please provide one in the format <image>:<tag> or <image>@sha256.."

    @mark.asyncio
    async def test_create_task_space_name_fails(
            self,
            post_json_admin_header,
            client,
            task_body,
            container,
            cr_name,
            registry,
            tags_request,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns an error when name is empty or null
        or one or more spaces
        """
        task_body["name"] = None
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        json_resp = response.json()
        assert "name" in json_resp["error"][0]["field"]
        assert json_resp["error"][0]["message"] == "Input should be a valid string"

    @mark.asyncio
    async def test_create_task_no_db_query(
            self,
            post_json_admin_header,
            client,
            v1_task_mock,
            mock_args_k8s,
            registry_client,
            task_body,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 201, if the db_query field
        is not provided, the connection string is passed
        as env var instead of QUERY, FROM_DIALECT and TO_DIALECT.
        Also checks that only one init container is created for the
        folder creation in the PV
        """
        task_body.pop("db_query")
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]
        # The fetch_data init container should not be created
        assert len(pod_body.spec.init_containers) == 1
        assert pod_body.spec.init_containers[0].name == f"init-{response.json()["id"]}"
        envs = [env.name for env in pod_body.spec.containers[0].env]
        assert "CONNECTION_STRING" in envs
        assert set(envs).intersection({"QUERY", "FROM_DIALECT", "TO_DIALECT"}) == set()

    @mark.asyncio
    async def test_automatic_delivery_via_crd(
        self,
        registry_client,
        post_json_admin_header,
        set_task_other_delivery_allowed_env,
        client,
        v1_crd_mock,
        task_body,
        mock_args_crd,
        mock_kc_client_task_service
    ):
        """
        Tests that with the right conditions (from env variables)
        the auto delivery is performed
        """
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_crd.api_client.create_cluster_custom_object.assert_called()

    @mark.asyncio
    async def test_automatic_delivery_via_crd_is_not_performed(
        self,
        registry_client,
        post_json_admin_header,
        client,
        v1_crd_mock,
        task_body,
        mocker,
        mock_args_crd,
        mock_kc_client_task_service
    ):
        """
        Tests that with the missing conditions (from env variables)
        the auto delivery is not performed
        """
        mocker.patch(f'app.models.task.settings.task_controller', "enabled")

        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_crd.api_client.create_cluster_custom_object.assert_not_called()

        mocker.patch(f'app.models.task.settings.task_controller', None)
        mocker.patch(f'app.models.task.settings.auto_delivery_results', "enabled")

        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_crd.api_client.create_cluster_custom_object.assert_not_called()

    @mark.asyncio
    async def test_create_task_incomplete_db_query(
            self,
            post_json_admin_header,
            client,
            v1_task_mock,
            registry_client,
            task_body,
            mock_args_k8s,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns an error if the db_query is
        missing the mandatory field "query".
        """
        task_body["db_query"] = {}
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json()["error"] == "`db_query` field must include a `query`"
        mock_args_k8s.api_client.create_namespaced_pod.assert_not_called()

    @mark.asyncio
    async def test_create_task_invalid_output_field(
            self,
            post_json_admin_header,
            client,
            registry_client,
            task_body,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 4xx request when output
        is not a dictionary
        """
        task_body["outputs"] = []
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json() == {"error": "\"outputs\" filed muct be a json object or dictionary"}

    @mark.asyncio
    async def test_create_task_no_output_field_reverts_to_default(
            self,
            v1_task_mock,
            post_json_admin_header,
            client,
            registry_client,
            task_body,
            mock_args_k8s,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 201 but the volume mounted
        is the default one
        """
        task_body.pop("outputs")
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]
        assert len(pod_body.spec.containers[0].volume_mounts) == 1
        assert pod_body.spec.containers[0].volume_mounts[0].mount_path == settings.task_pod_results_path

    @mark.asyncio
    async def test_create_task_with_ds_name(
            self,
            post_json_admin_header,
            client,
            registry_client,
            dataset,
            task_body,
            mock_kc_client_task_service
        ):
        """
        Tests task creation with a dataset name returns 201
        """
        data = task_body
        data["tags"].pop("dataset_id")
        data["tags"]["dataset_name"] = dataset.name

        response = await client.post(
            '/tasks',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 201

    @mark.asyncio
    async def test_create_task_with_ds_name_and_id(
            self,
            post_json_admin_header,
            client,
            registry_client,
            dataset,
            task_body,
            mock_kc_client_task_service
        ):
        """
        Tests task creation with a dataset name and id returns 201
        """
        data = task_body
        data["tags"]["dataset_name"] = dataset.name

        response = await client.post(
            '/tasks',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 201

    @mark.asyncio
    async def test_create_task_with_conflicting_ds_name_and_id(
            self,
            post_json_admin_header,
            client,
            dataset,
            registry_client,
            task_body,
            mock_kc_client_task_service
        ):
        """
        Tests task creation with a dataset name that does not exists
        and a valid id returns 201
        """
        expected_msg = f"Dataset \"something else\" with id {dataset.id} does not exist"
        data = task_body
        data["tags"]["dataset_name"] = "something else"

        response = await client.post(
            '/tasks',
            json=data,
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json()["error"] == expected_msg

    @mark.asyncio
    async def test_create_task_with_non_existing_dataset(
            self,
            post_json_admin_header,
            client,
            task_body,
            registry_client,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 404 when the requested dataset doesn't exist
        """
        data = task_body
        data["tags"]["dataset_id"] += 1

        response = await client.post(
            '/tasks',
            json=data,
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json() == {"error": f"Dataset {data["tags"]["dataset_id"]} does not exist"}

    @mark.asyncio
    async def test_create_task_with_non_existing_dataset_name(
            self,
            post_json_admin_header,
            client,
            dataset,
            task_body,
            registry_client,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 404 when the
        requested dataset name doesn't exist
        """
        data = task_body
        data["tags"].pop("dataset_id")
        data["tags"]["dataset_name"] = "something else"

        response = await client.post(
            '/tasks',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json() == {"error": "Dataset something else does not exist"}

    @patch('app.helpers.wrappers.Keycloak.create.is_token_valid', return_value=False)
    @mark.asyncio
    async def test_create_unauthorized_task(
            self,
            kc_valid_mock,
            post_json_user_header,
            dataset,
            client,
            task_body,
            base_kc_mock_args,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 403 if a user is not authorized to
        access the dataset
        """
        data = task_body
        data["dataset_id"] = dataset.id

        base_kc_mock_args.is_token_valid.return_value = False

        response = await client.post(
            '/tasks',
            data=json.dumps(data),
            headers=post_json_user_header
        )
        assert response.status_code == 403

    @mark.asyncio
    async def test_create_task_image_with_digest(
            self,
            post_json_admin_header,
            client,
            v1_task_mock,
            registry_client,
            mock_args_k8s,
            mock_args_crd,
            container_with_sha,
            task_body,
            v1_crd_mock,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 201 with the image sha rather than
        an image tag
        """
        task_body["executors"][0]["image"] = container_with_sha.full_image_name()
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        mock_args_crd.api_client.create_cluster_custom_object.assert_not_called()

    @mark.asyncio
    async def test_create_task_image_same_name_different_registry(
            self,
            v1_task_mock,
            registry_client,
            post_json_admin_header,
            client,
            container,
            task_body,
            db_session,
            mock_kc_client_task_service
        ):
        """
        Tests task creation is successful if two images are mapped with the
        same name, but different registry
        """
        registry = Registry(url="another.azurecr.io", username="user", password="pass")
        await registry.add(db_session)
        await Container(registry=registry, name=container.name, tag=container.tag).add(db_session)
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201

    @mark.asyncio
    async def test_create_task_image_not_found(
            self,
            cr_client_404,
            post_json_admin_header,
            client,
            task_body,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 500 with a requested docker image is not found
        """
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 500
        assert response.json() == {"error": f"Image {task_body["executors"][0]["image"]} not found on our repository"}

    @mark.asyncio
    async def test_create_task_inputs_not_default(
            self,
            post_json_admin_header,
            client,
            registry_client,
            v1_task_mock,
            task_body,
            mock_args_k8s,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 201 and if users provide
        custom location for inputs, this is set as volumeMount
        """
        task_body["inputs"] = {"file.csv": "/data/in"}
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]

        assert len(pod_body.spec.containers[0].volume_mounts) == 2
        # Check if the mount volume is on the correct path
        assert "/data/in" in [vm.mount_path for vm in pod_body.spec.containers[0].volume_mounts]
        # Check if the INPUT_PATH variable is set
        assert ["/data/in/file.csv"] == [ev.value for ev in pod_body.spec.containers[0].env if ev.name == "INPUT_PATH"]

    @mark.asyncio
    async def test_create_task_input_path_env_var_override(
            self,
            post_json_admin_header,
            client,
            registry_client,
            v1_task_mock,
            task_body,
            mock_args_k8s,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 201 and if users provide
        INPUT_PATH as a env var, use theirs
        """
        task_body["executors"][0]["env"] = {"INPUT_PATH": "/data/in/file.csv"}
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]

        # Check if the INPUT_PATH variable is set
        assert ["/data/in/file.csv"] == [ev.value for ev in pod_body.spec.containers[0].env if ev.name == "INPUT_PATH"]

    @mark.asyncio
    async def test_create_task_invalid_output_field(
            self,
            post_json_admin_header,
            client,
            registry_client,
            task_body,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 4xx request when output
        is not a dictionary
        """
        task_body["outputs"] = []
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json() == {"error": "\"outputs\" field must be a json object or dictionary"}

    @mark.asyncio
    async def test_create_task_invalid_inputs_field(
            self,
            post_json_admin_header,
            client,
            registry_client,
            task_body,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 4xx request when inputs
        is not a dictionary
        """
        task_body["inputs"] = []
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json() == {"error": "\"inputs\" field must be a json object or dictionary"}

    @mark.asyncio
    async def test_create_task_no_output_field_reverts_to_default(
            self,
            v1_task_mock,
            post_json_admin_header,
            client,
            registry_client,
            task_body,
            mock_args_k8s,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 201 but the resutls volume mounted
        is the default one
        """
        task_body.pop("outputs")
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]
        assert len(pod_body.spec.containers[0].volume_mounts) == 2
        assert settings.task_pod_results_path in [vm.mount_path for vm in pod_body.spec.containers[0].volume_mounts]

    @mark.asyncio
    async def test_create_task_no_inputs_field_reverts_to_default(
            self,
            v1_task_mock,
            post_json_admin_header,
            client,
            registry_client,
            task_body,
            mock_args_k8s,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 201 but the volume mounted
        is the default one for the inputs
        """
        task_body.pop("inputs")
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]
        assert len(pod_body.spec.containers[0].volume_mounts) == 2
        assert [vm.mount_path for vm in pod_body.spec.containers[0].volume_mounts] == ["/mnt/inputs", settings.task_pod_results_path]

    @mark.asyncio
    async def test_create_task_controller_not_deployed_no_crd(
            self,
            post_json_admin_header,
            client,
            registry_client,
            k8s_client,
            task_body,
            v1_crd_mock,
            mock_kc_client_task_service,
            mock_args_crd
        ):
        """
        Tests task creation returns 201. It should not try to
        create a CRD if the task controller is not deployed
        """
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()

    @mark.asyncio
    async def test_create_task_controller_deployed_create_crd(
            self,
            post_json_admin_header,
            client,
            registry_client,
            set_task_controller_env,
            k8s_client,
            task_body,
            v1_crd_mock,
            mock_args_crd,
            mock_kc_client_task_service
        ):
        """
        Tests task creation returns 201. It should try to
        create a CRD if the task controller is deployed
        """
        response = await client.post(
            '/tasks',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_crd.api_client.create_cluster_custom_object.assert_called()

    @mark.asyncio
    async def test_create_task_from_controller(
            self,
            post_json_admin_header,
            client,
            registry_client,
            k8s_client,
            v1_crd_mock,
            task_body,
            mock_kc_client_task_service,
            mock_args_crd
        ):
        """
        Tests task creation returns 201. Should be consistent
        with or without the task_controller flag
        """
        task_body["task_controller"] = True
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_crd.api_client.create_cluster_custom_object.assert_not_called()

    @mark.asyncio
    async def test_task_dataset_with_repo(
            self,
            post_json_admin_header,
            client,
            registry_client,
            k8s_client,
            v1_crd_mock,
            task_body,
            dataset_with_repo,
            mock_kc_client_task_service,
            mock_args_crd
        ):
        """
        Simple test to make sure the task triggers with a specific dataset repo
        """
        task_body["task_controller"] = True
        task_body["tags"] = {}
        task_body["repository"] = "organisation/repository"
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        mock_args_crd.api_client.create_cluster_custom_object.assert_not_called()

    @mark.asyncio
    async def test_task_dataset_with_repo_unlinked(
            self,
            post_json_admin_header,
            client,
            registry_client,
            k8s_client,
            v1_crd_mock,
            task_body,
            dataset_with_repo,
            mock_kc_client_task_service,
            mock_args_crd
        ):
        """
        Simple test to make sure the task is not created if the repository provided
        has no dataset linked to it
        """
        task_body["task_controller"] = True
        task_body["tags"] = {}
        task_body["repository"] = "organisation/repository2"
        response = await client.post(
            '/tasks',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json()["error"] == "No datasets linked with the repository organisation/repository2"
        mock_args_crd.api_client.create_cluster_custom_object.assert_not_called()

    @mark.asyncio
    async def test_task_schema_env_variables(
            self,
            task,
            v1_task_mock,
            registry_client,
            mock_args_k8s,
            mock_kc_client_task_service
    ):
        """
        Simple test to make sure the environment passed to the pod includes
        the two schemas, regardless of their value
        """
        task.db_query = None
        await task.run()
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]
        env = [env.name for env in pod_body.spec.containers[0].env if re.match(".+_SCHEMA", env.name)]
        assert len(set(env).intersection({"CDM_SCHEMA", "WRITE_SCHEMA"})) == 2

    @mark.asyncio
    async def test_task_connection_string_postgres(
            self,
            task,
            v1_task_mock,
            registry_client,
            mock_args_k8s,
            mock_kc_client_task_service
    ):
        """
        Simple test to make sure the generated connection string
        follows the global format
        """
        task.db_query = None
        await task.run()
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]
        env = [env.value for env in pod_body.spec.containers[0].env if env.name == "CONNECTION_STRING"][0]
        assert re.match(r'driver={PostgreSQL ANSI};Uid=.*;Pwd=.*;Server=.*;Database=.*;$', env) is not None

    @mark.asyncio
    async def test_task_connection_string_oracle(
            self,
            task_oracle,
            v1_task_mock,
            registry_client,
            mock_args_k8s,
            mock_kc_client_task_service
    ):
        """
        Simple test to make sure the generated connection string
        follows the specific format for OracleDB
        """
        task_oracle.db_query = None
        await task_oracle.run()
        mock_args_k8s.api_client.create_namespaced_pod.assert_called()
        pod_body = mock_args_k8s.api_client.create_namespaced_pod.call_args.kwargs["body"]
        env = [env.value for env in pod_body.spec.containers[0].env if env.name == "CONNECTION_STRING"][0]
        assert re.match(r'driver={Oracle ODBC Driver};Uid=.*;PSW=.*;DBQ=.*;$', env) is not None


class TestCancelTask:
    @mark.asyncio
    async def test_cancel_task(
            self,
            client,
            simple_admin_header,
            task,
            v1_task_mock,
            mock_kc_client_task_service
        ):
        """
        Test that an admin can cancel an existing task
        """
        response = await client.post(
            f'/tasks/{task.id}/cancel',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert "cancelled" in response.json()["status"]

    @mark.asyncio
    async def test_cancel_404_task(
            self,
            client,
            simple_admin_header,
            mock_kc_client_task_service
        ):
        """
        Test that an admin can cancel a non-existing task returns a 404
        """
        response = await client.post(
            '/tasks/123456/cancel',
            headers=simple_admin_header
        )
        assert response.status_code == 404


class TestValidateTask:
    @mark.asyncio
    async def test_validate_task(
            self,
            client,
            task_body,
            registry_client,
            post_json_admin_header,
            mock_kc_client_task_service
        ):
        """
        Test the validation endpoint can be used by admins returns 201
        """
        response = await client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 200

    @mark.asyncio
    async def test_validate_task_admin_missing_dataset(
            self,
            client,
            task_body,
            registry_client,
            post_json_admin_header,
            mock_kc_client_task_service
        ):
        """
        Test the validation endpoint can be used by admins returns
        an error message if the dataset info is not provided
        """
        task_body["tags"].pop("dataset_id")
        response = await client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Administrators need to provide `tags.dataset_id` or `tags.dataset_name`"

    @mark.asyncio
    async def test_validate_task_basic_user(
            self,
            client,
            task_body,
            registry_client,
            post_json_user_header: dict[str, str],
            access_request,
            user_uuid,
            base_kc_mock_args,
            mock_kc_client_task_service
        ):
        """
        Test the validation endpoint can be used by non-admins returns 201
        """
        base_kc_mock_args.get_user_by_username.return_value = {"id": user_uuid}

        post_json_user_header["project-name"] = access_request.project_name
        response = await client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_user_header
        )
        assert response.status_code == 200, response.json()


class TestTasksLogs:
    @mark.asyncio
    async def test_task_get_logs(
            self,
            post_json_admin_header,
            client,
            mocker,
            terminated_state,
            task,
            v1_task_mock,
            mock_kc_client_task_service
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
        response_logs = await client.get(
            f'/tasks/{task.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 200
        assert response_logs.json()["logs"] == [
            'Example logs',
            'another line'
        ]

    @mark.asyncio
    async def test_task_logs_non_existent(
            self,
            post_json_admin_header,
            client,
            task,
            v1_task_mock,
            mock_kc_client_task_service
        ):
        """
        Basic test that will check the appropriate error
        is returned when the task id does not exist
        """
        response_logs = await client.get(
            f'/tasks/{task.id + 1}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 404
        assert response_logs.json()["error"] == f"Task with id {task.id + 1} does not exist"

    @mark.asyncio
    async def test_task_waiting_get_logs(
            self,
            post_json_admin_header,
            client,
            mocker,
            waiting_state,
            task,
            v1_task_mock,
            pod_listed,
            mock_args_k8s,
            mock_kc_client_task_service
        ):
        """
        Basic test that will try to get logs for a pod
        in an init state.
        """
        pod_listed.status.container_statuses = [waiting_state]
        response_logs = await client.get(
            f'/tasks/{task.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 200
        assert response_logs.json()["logs"] == 'Task queued'

    @mark.asyncio
    async def test_task_not_found_get_logs(
            self,
            post_json_admin_header,
            client,
            mocker,
            task,
            v1_task_mock,
            mock_kc_client_task_service
        ):
        """
        Basic test that will try to get the logs from a missing
        pod. This can happen if the task gets cleaned up
        """
        mocker.patch(
            'app.models.task.Task.get_current_pod',
            return_value=None
        )
        response_logs = await client.get(
            f'/tasks/{task.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 400
        assert response_logs.json()["error"] == f'Task pod {task.id} not found'

    @mark.asyncio
    async def test_task_get_logs_fails(
            self,
            post_json_admin_header,
            client,
            k8s_client,
            mocker,
            task,
            terminated_state,
            v1_task_mock,
            mock_args_k8s,
            mock_kc_client_task_service
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
        mock_args_k8s.api_client.read_namespaced_pod_log.side_effect = ApiException()
        response_logs = await client.get(
            f'/tasks/{task.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 500
        assert response_logs.json()["error"] == 'Failed to fetch the logs'
