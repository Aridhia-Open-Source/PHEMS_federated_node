from datetime import datetime
from kubernetes.client.exceptions import ApiException

import json
from datetime import datetime
from pytest import fixture
from copy import deepcopy
from unittest.mock import Mock

from app.models.task import Task


@fixture(scope='function')
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

@fixture
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

@fixture
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

@fixture
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

@fixture
def results_job_mock(mocker, task_body, reg_k8s_client):
    mocker.patch(
        'app.models.task.Task.get_status',
        return_value={"running": {}}
    )
    mocker.patch('app.models.task.uuid4', return_value="1dc6c6d1-417f-409a-8f85-cb9d20f7c741")

    pod_mock = Mock()
    pod_mock.metadata.labels = {"job-name": "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"}
    pod_mock.metadata.name = "result-job-1dc6c6d1-417f-409a-8f85-cb9d20f7c741"
    pod_mock.spec.containers = [Mock(image=task_body["executors"][0]["image"])]
    pod_mock.status.container_statuses = [Mock(ready=True)]

    reg_k8s_client["list_namespaced_pod_mock"].return_value.items = [pod_mock]
    return pod_mock

@fixture
def task_mock(dataset, user_uuid, container):
    task = Task(
        name="Test Task",
        docker_image=container.full_image_name(),
        description="something",
        requested_by=user_uuid,
        dataset=dataset,
        created_at=datetime.now()
    )
    task.add()
    return task

@fixture
def k8s_crd_500():
    return ApiException(
        http_resp=Mock(
            status=500,
            reason="Error",
            data=json.dumps({
                "details": {
                    "causes": [
                        {
                            "message": "Failed to patch the CRD"
                        }
                    ]
                }
            })
        )
    )

@fixture
def k8s_crd_404():
    return ApiException(
        http_resp=Mock(
            status=404,
            reason="Error",
            data=json.dumps({
                "details": {
                    "causes": [
                        {
                            "message": "Not Found",
                        }
                    ]
                }
            })
        )
    )

@fixture
def set_task_review_env(mocker):
    mocker.patch('app.models.task.TASK_REVIEW', return_value="enabled")
    mocker.patch('app.tasks_api.TASK_REVIEW', return_value="enabled")

@fixture
def set_task_controller_env(mocker):
    mocker.patch('app.models.task.TASK_CONTROLLER', return_value="enabled")
