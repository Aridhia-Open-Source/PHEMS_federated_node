import json
from unittest import mock
from unittest.mock import Mock

from app.helpers.const import TASK_POD_RESULTS_PATH
from app.helpers.db import db
from app.models.task import Task
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


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

def test_create_task_from_controller(
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

def test_create_task_with_delivery(
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
    task_body["deliver_to"] = {
        "other": {
            "url": "something.com",
            "auth_type": "Bearer"
        }
    }
    response = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_admin_header
    )
    assert response.status_code == 201

def test_create_task_with_delivery_missing_fields(
        cr_client,
        post_json_admin_header,
        client,
        registry_client,
        task_body,
        k8s_client
    ):
    """
    Tests task creation returns 201. Should be consistent
    with or without the task_controller flag
    """
    k8s_client["create_cluster_custom_object"].side_effect = ApiException(
        http_resp=Mock(
            status=400,
            reason="Error",
            data=json.dumps({
                "details": {
                    "causes": [
                        {
                            "message": "Required value",
                            "field": "spec.results.auth_type"
                        }
                    ]
                }
            }))
    )
    task_body["deliver_to"] = {
        "other": {
            "url": "something.com"
        }
    }
    response = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_admin_header
    )
    assert response.status_code == 400
    assert response.json["error"] == {'Missing values': ['deliver_to.auth_type']}

def test_create_task_with_delivery_top_level_only(
        cr_client,
        post_json_admin_header,
        client,
        registry_client,
        task_body,
        k8s_client
    ):
    """
    Tests task creation returns 201. Should be consistent
    with or without the task_controller flag
    """
    error_message = "Unsupported value. Only accepting \"Bearer\", \"AzCopy\" and \"Basic\""
    k8s_client["create_cluster_custom_object"].side_effect = ApiException(
        http_resp=Mock(
            status=400,
            reason="Error",
            data=json.dumps({
                "details": {
                    "causes": [
                        {
                            "message": error_message
                        }
                    ]
                }
            }))
    )
    task_body["deliver_to"] = {
        "other": {
            "url": "something.com",
            "auth_type": "somethingelse"
        }
    }
    response = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_admin_header
    )
    assert response.status_code == 400
    assert response.json["error"] == [error_message]

def test_create_task_with_delivery_wrong_format(
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
    task_body["deliver_to"] = True
    response = client.post(
        '/tasks/',
        data=json.dumps(task_body),
        headers=post_json_admin_header
    )
    assert response.status_code == 400
    assert response.json["error"] == "`deliver_to` must have either `git` or `other` as field"

def test_create_task_invalid_output_field(
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

@mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
def test_get_task_by_id_admin(
        token_valid_mock,
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

@mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
def test_get_task_by_id_non_admin_owner(
        token_valid_mock,
        cr_client,
        simple_user_header,
        post_json_user_header,
        client,
        registry_client,
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

@mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
def test_get_task_by_id_non_admin_non_owner(
        token_valid_mock,
        cr_client,
        post_json_user_header,
        simple_user_header,
        client,
        registry_client,
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
        registry_client,
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

def test_validate_task_basic_user(
        client,
        task_body,
        cr_client,
        registry_client,
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

def test_get_task_status_running_and_waiting(
    cr_client,
    registry_client,
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
    registry_client,
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
