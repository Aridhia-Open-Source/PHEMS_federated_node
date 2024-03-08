import json
import pytest
from kubernetes.client.exceptions import ApiException
from unittest.mock import Mock
from app.helpers.exceptions import InvalidRequest
from app.models.task import Task
from tests.helpers.kubernetes import MockKubernetesClient


@pytest.fixture(scope='function')
def task_body(dataset):
    return {
        "name": "Test Task",
        "requested_by": "das9908-as098080c-9a80s9",
        "executors": [
            {
                "image": "example:latest",
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
    assert response.status_code == 401

def test_create_task(
        acr_client,
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

def test_create_task_with_non_existing_dataset(
        acr_client,
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
    assert response.json == {"error": "Dataset with id 123456 does not exist"}

def test_create_unauthorized_task(
        acr_client,
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
    assert response.status_code == 401

def test_create_task_image_not_found(
        acr_client_404,
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

def test_cancel_task(
        client,
        acr_client,
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
        acr_client,
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
        acr_client,
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
        acr_client,
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

def test_get_results(
    acr_client,
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
    k8s_client.return_value.list_namespaced_pod.return_value.items = [pod_mock]

    response = client.get(
        f'/tasks/{response.json["task_id"]}/results',
        headers=simple_admin_header
    )
    assert response.status_code == 200
    assert response.content_type == "application/x-tar"

def test_get_results_job_creation_failure(
    acr_client,
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

    response = client.get(
        f'/tasks/{response.json["task_id"]}/results',
        headers=simple_admin_header
    )
    assert response.status_code == 500
    assert response.json["error"] == 'Failed to run pod: Something went wrong'

def test_get_task_status_running_and_waiting(
    acr_client,
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
    acr_client,
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
