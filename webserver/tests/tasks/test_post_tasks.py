import json
import re
from unittest import mock

from app.helpers.const import TASK_POD_RESULTS_PATH
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


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

    def test_create_task_incomplete_db_query(
            self,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns an error if the db_query is
        missing the mandatory field "query".
        """
        task_body["db_query"] = {}
        response = client.post(
            '/tasks/',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "`db_query` field must include a `query`"
        reg_k8s_client["create_namespaced_pod_mock"].assert_not_called()

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
            task_body,
            mock_kc_client
        ):
        """
        Tests task creation returns 403 if a user is not authorized to
        access the dataset
        """
        data = task_body
        data["dataset_id"] = dataset.id

        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_user_header
        )
        assert response.status_code == 403

    def test_create_task_image_with_digest(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            container_with_sha,
            task_body,
            v1_crd_mock
        ):
        """
        Tests task creation returns 201 with the image sha rather than
        an image tag
        """
        task_body["executors"][0]["image"] = container_with_sha.full_image_name()
        response = client.post(
            '/tasks/',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()

    def test_create_task_image_same_name_different_registry(
            self,
            cr_client,
            reg_k8s_client,
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
        registry = Registry(url="another.azurecr.io", username="user", password="pass")
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
        task_body["crd_name"] = "crd name test"
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()

    def test_create_task_from_controller_missing_name(
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
        Tests task creation returns an error if the mandatory crd_name field
        is not provided from the controller
        """
        task_body["task_controller"] = True
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "Missing crd name in the request, or None passed"
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()

    def test_task_dataset_with_repo(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            k8s_client,
            v1_crd_mock,
            task_body,
            dataset_with_repo
        ):
        """
        Simple test to make sure the task triggers with a specific dataset repo
        """
        task_body["task_controller"] = True
        task_body["tags"] = {}
        task_body["repository"] = "organisation/repository"
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()

    def test_task_dataset_with_repo_unlinked(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            k8s_client,
            v1_crd_mock,
            task_body,
            dataset_with_repo
        ):
        """
        Simple test to make sure the task is not created if the repository provided
        has no dataset linked to it
        """
        task_body["task_controller"] = True
        task_body["tags"] = {}
        task_body["repository"] = "organisation/repository2"
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "No datasets linked with the repository organisation/repository2"
        v1_crd_mock.return_value.create_cluster_custom_object.assert_not_called()

    def test_task_schema_env_variables(
            self,
            task,
            cr_client,
            reg_k8s_client,
            registry_client
    ):
        """
        Simple test to make sure the environment passed to the pod includes
        the two schemas, regardless of their value
        """
        task.db_query = None
        task.run()
        reg_k8s_client["create_namespaced_pod_mock"].assert_called()
        pod_body = reg_k8s_client["create_namespaced_pod_mock"].call_args.kwargs["body"]
        env = [env.name for env in pod_body.spec.containers[0].env if re.match(".+_SCHEMA", env.name)]
        assert len(set(env).intersection({"CDM_SCHEMA", "WRITE_SCHEMA"})) == 2

    def test_task_connection_string_postgres(
            self,
            task,
            cr_client,
            reg_k8s_client,
            registry_client
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
