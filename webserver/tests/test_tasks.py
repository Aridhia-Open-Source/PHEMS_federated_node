import json
import pytest
from datetime import datetime, timedelta
from kubernetes.client.exceptions import ApiException
from unittest import mock
from unittest.mock import Mock

from app.helpers.const import CLEANUP_AFTER_DAYS
from app.helpers.db import db
from app.helpers.exceptions import InvalidRequest
from app.models.task import Task
from tests.helpers.kubernetes import MockKubernetesClient


@pytest.fixture(scope='function')
def task_body(dataset, image_name):
    return {
        "name": "Test Task",
        "requested_by": "das9908-as098080c-9a80s9",
        "executors": [
            {
                "image": image_name,
                "command": ["R", "-e", "df <- as.data.frame(installed.packages())[,c('Package', 'Version')];write.csv(df, file='/mnt/data/packages.csv', row.names=FALSE);Sys.sleep(10000)\""],
                "env": {
                    "VARIABLE_UNIQUE": 123,
                    "USERNAME": "test"
                }
            }
        ],
        "description": "First task ever!",
        "tags": {
            "dataset_id": dataset.id,
            "test_tag": "some content"
        },
        "inputs":{},
        "outputs":{},
        "resources": {},
        "volumes": {},
    }

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

def test_get_list_tasks(
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

def test_create_task(
        cr_client,
        k8s_client_task,
        post_json_admin_header,
        client,
        task_body
    ):
    """
    Tests task creation returns 201
    """
    data = task_body

    response = client.post(
        '/tasks/',
        data=json.dumps(data),
        headers=post_json_admin_header
    )
    assert response.status_code == 201

def test_create_task_with_ds_name(
        cr_client,
        k8s_client_task,
        post_json_admin_header,
        client,
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
        cr_client,
        k8s_client_task,
        post_json_admin_header,
        client,
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
        cr_client,
        k8s_client_task,
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
        kc_valid_mock,
        cr_client,
        post_json_user_header,
        dataset,
        client,
        task_body
    ):
    """
    Tests task creation returns 201
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

def test_get_task_by_id_admin(
        cr_client,
        k8s_client_task,
        post_json_admin_header,
        post_json_user_header,
        simple_admin_header,
        client,
        task_body
    ):
    """
    If an admin wants to check a specific task they should be allowed regardless
    of who requested it
    """
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

def test_get_task_by_id_non_admin_owner(
        cr_client,
        k8s_client_task,
        simple_user_header,
        post_json_user_header,
        client,
        task_body
    ):
    """
    If a user wants to check a specific task they should be allowed if they did request it
    """
    resp = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_user_header
    )
    assert resp.status_code == 201
    task_id = resp.json["task_id"]

    resp = client.get(
        f'/tasks/{task_id}',
        headers=simple_user_header
    )
    assert resp.status_code == 200

def test_get_task_by_id_non_admin_non_owner(
        cr_client,
        k8s_client_task,
        post_json_user_header,
        simple_user_header,
        client,
        task_body
    ):
    """
    If a user wants to check a specific task they should not be allowed if they did not request it
    """
    resp = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_user_header
    )
    assert resp.status_code == 201
    task_id = resp.json["task_id"]

    task_obj = db.session.get(Task, task_id)
    task_obj.requested_by = "some random uuid"

    resp = client.get(
        f'/tasks/{task_id}',
        headers=simple_user_header
    )
    assert resp.status_code == 403

def test_cancel_task(
        client,
        cr_client,
        k8s_client_task,
        simple_admin_header,
        post_json_admin_header,
        task_body
    ):
    """
    Test that an admin can cancel an existing task
    """
    response = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_admin_header
    )
    assert response.status_code == 201

    response = client.post(
        f'/tasks/{response.json['task_id']}/cancel',
        headers=simple_admin_header
    )
    assert response.status_code == 201

def test_cancel_404_task(
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

def test_validate_task(
        client,
        task_body,
        cr_client,
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

def test_validate_task_basic_user(
        client,
        task_body,
        cr_client,
        post_json_user_header
    ):
    """
    Test the validation endpoint can be used by non-admins returns 201
    """
    response = client.post(
        '/tasks/validate',
        data=json.dumps(task_body),
        headers=post_json_user_header
    )
    assert response.status_code == 200

def test_docker_image_regex(
        task_body,
        cr_client,
        mocker,
        client
):
    """
    Tests that the docker image is in an expected format
        <namespace?/image>:<tag>
    """
    data = task_body
    valid_image_formats = [
        "image:3.21",
        "namespace/image:3.21",
        "namespace/image:3.21-alpha"
    ]
    invalid_image_formats = [
        "not_valid/",
        "/not-valid:",
        "/not-valid:2.31",
        "image",
        "namespace//image:3.21",
        "/image"
    ]
    mocker.patch(
        'app.models.task.Keycloak',
        return_value=Mock()
    )
    for im_format in valid_image_formats:
        data["executors"][0]["image"] = im_format
        Task.validate(data)

    for im_format in invalid_image_formats:
        data["executors"][0]["image"] = im_format
        with pytest.raises(InvalidRequest):
            Task.validate(data)


class TestTaskResults:
    def test_get_results(
        self,
        cr_client,
        post_json_admin_header,
        simple_admin_header,
        client,
        task_body,
        mocker
    ):
        """
        A simple test with mocked PVs to test a successful result
        fetch
        """
        # Create a new task
        data = task_body
        # The mock has to be done manually rather than use the fixture
        # as it complains about the return value of the list_pod method
        mocker.patch(
            'app.models.task.KubernetesClient',
            return_value=MockKubernetesClient()
        )
        mocker.patch('app.models.task.uuid4', return_value="1dc6c6d1-417f-409a-8f85-cb9d20f7c741")
        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 201

        # Get results
        mocker.patch(
            'app.models.task.KubernetesBatchClient'
        )
        k8s_client = mocker.patch(
            'app.models.task.KubernetesClient',
            return_value=Mock(list_namespaced_pod=Mock())
        )
        pod_mock = Mock()
        pod_mock.metadata.labels = {"job-name": "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"}
        pod_mock.metadata.name = "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"
        pod_mock.spec.containers = [Mock(image=task_body["executors"][0]["image"])]
        pod_mock.status.container_statuses = [Mock(ready=True)]
        k8s_client.return_value.list_namespaced_pod.return_value.items = [pod_mock]

        mocker.patch(
            'app.models.task.Task.get_status',
            return_value={"running": {}}
        )

        response = client.get(
            f'/tasks/{response.json["task_id"]}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.content_type == "application/x-tar"

    def test_get_results_job_creation_failure(
        self,
        cr_client,
        post_json_admin_header,
        simple_admin_header,
        client,
        task_body,
        mocker
    ):
        """
        Tests that the job creation to fetch results from a PV returns a 500
        error code
        """
        # Create a new task
        data = task_body
        # The mock has to be done manually rather than use the fixture
        # as it complains about the return value of the list_pod method
        mocker.patch(
            'app.models.task.KubernetesClient',
            return_value=MockKubernetesClient()
        )
        response = client.post(
            '/tasks/',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 201

        # Get results - creating a job fails
        k8s_batch = mocker.patch('app.models.task.KubernetesBatchClient')
        k8s_batch.return_value.create_namespaced_job.side_effect = ApiException(status=500, reason="Something went wrong")

        k8s_client = mocker.patch(
            'app.models.task.KubernetesClient',
            return_value=Mock(list_namespaced_pod=Mock())
        )
        pod_mock = Mock()
        pod_mock.metadata.labels = {"job-name": "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"}
        pod_mock.metadata.name = "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"
        pod_mock.spec.containers = [Mock(image=task_body["executors"][0]["image"])]
        pod_mock.status.container_statuses = [Mock(ready=True)]
        k8s_client.return_value.list_namespaced_pod.return_value.items = [pod_mock]

        response = client.get(
            f'/tasks/{response.json["task_id"]}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == 'Failed to run pod: Something went wrong'

    def test_results_not_found_with_expired_date(
        self,
        simple_admin_header,
        client,
        dataset
    ):
        """
        A task result are being deleted after a declared number of days.
        This test makes sure an error is returned as expected
        """
        task = Task(
            name="task",
            docker_image="image:tag",
            description="something",
            requested_by="abc123-412-51251-213-412",
            dataset=dataset,
            created_at=datetime.now() - timedelta(days=CLEANUP_AFTER_DAYS)
        )
        task.add()
        response = client.get(
            f'/tasks/{task.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 500
        assert response.json["error"] == 'Tasks results are not available anymore. Please, run the task again'

def test_get_task_status_running_and_waiting(
    cr_client,
    k8s_client_task,
    running_state,
    waiting_state,
    post_json_admin_header,
    client,
    task_body,
    mocker
):
    """
    Test to verify the correct task status when it's
    waiting or Running on k8s. Output would be similar
    """
    response = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_admin_header
    )
    assert response.status_code == 201

    mocker.patch(
        'app.models.task.Task.get_current_pod',
        return_value=Mock(
            status=Mock(
                container_statuses=[running_state]
            )
        )
    )

    response_id = client.get(
        f'/tasks/{response.json["task_id"]}',
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
        f'/tasks/{response.json["task_id"]}',
        data=json.dumps(task_body),
        headers=post_json_admin_header
    )
    assert response_id.status_code == 200
    assert response_id.json["status"] == {'waiting': {'started_at': '1/1/2024'}}

def test_get_task_status_terminated(
    cr_client,
    k8s_client_task,
    terminated_state,
    post_json_admin_header,
    client,
    task_body,
    mocker
):
    """
    Test to verify the correct task status when it's terminated on k8s
    """
    response = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_admin_header
    )
    assert response.status_code == 201

    mocker.patch(
        'app.models.task.Task.get_current_pod',
        return_value=Mock(
            status=Mock(
                container_statuses=[terminated_state]
            )
        )
    )

    response_id = client.get(
        f'/tasks/{response.json["task_id"]}',
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

class TestResourceValidators:
    def test_valid_values(
            self,
            mocker,
            user_uuid,
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
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})
        Task.validate(task_body)

    def test_invalid_memory_values(
            self,
            mocker,
            user_uuid,
            cr_client,
            task_body
        ):
        """
        Tests that the unexpected memory values are not accepted
        """
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})

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
            user_uuid,
            cr_client,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})

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
            user_uuid,
            cr_client,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})

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
            user_uuid,
            cr_client,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})

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
