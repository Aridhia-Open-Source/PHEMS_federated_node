"""
A run's Secret and ConfigMap in the tasks namespace: POST /projects/<id>/tasks/<id>/runs/<run_id>/resources
creates them, labelled and named per run, and a task reaching SUCCESS, FAILED or CANCELED (PATCH) deletes them
by the run label (helpers/task_resources.py).
"""
import json

import pytest
from kubernetes.client.exceptions import ApiException

from app.helpers.base_model import db
from app.models.task import Task
from tests.conftest import CONTRACT_DIR

RUN_ID = "5b1f8c2e-0d3a-4c57-9a5e-6f2d1c7b8a90"
NAMESPACE = "tasks"
CONTRACT = CONTRACT_DIR / "task_resources_response.json"


@pytest.fixture
def dataset_task(make_task, dataset):
    return make_task(dataset_id=dataset.id)


@pytest.fixture
def config_task(make_task):
    task = make_task()
    task.spec.config = {"threshold": 3}
    db.session.commit()
    return task


def resources_url(project, task, run_id=RUN_ID) -> str:
    return f"/projects/{project.id}/tasks/{task.id}/runs/{run_id}/resources"


def create(client, headers, project, task, run_id=RUN_ID):
    return client.post(resources_url(project, task, run_id), headers=headers)


# --------------------------------------------------------------------------- create


def test_a_task_with_a_dataset_and_a_config_gets_a_secret_and_a_configmap_labelled_for_the_run(
        client, system_headers, project, dataset_task, k8s_client):
    dataset_task.spec.config = {"threshold": 3}
    db.session.commit()

    response = create(client, system_headers, project, dataset_task)

    name = f"task-{dataset_task.id}-{RUN_ID}"
    assert response.status_code == 201, response.json()
    assert response.json() == {"secret": name, "config_map": f"{name}-config"}
    labels = {"fn/run_id": RUN_ID, "fn/task_id": str(dataset_task.id)}

    namespace, secret = k8s_client["create_namespaced_secret_mock"].call_args.args
    assert namespace == NAMESPACE
    assert (secret.metadata.name, secret.metadata.labels) == (name, labels)
    # the credentials of the dataset's secret ("abc123" in the k8s_client fixture), written here and never returned
    assert secret.string_data == {"USERNAME": "abc123", "PASSWORD": "abc123"}
    assert "abc123" not in response.text

    namespace, config_map = k8s_client["create_namespaced_config_map_mock"].call_args.args
    assert namespace == NAMESPACE
    assert (config_map.metadata.name, config_map.metadata.labels) == (f"{name}-config", labels)
    assert config_map.data == {"config.json": json.dumps({"threshold": 3})}


def test_the_response_has_the_shape_dagsters_task_resources_parses(client, system_headers, project, dataset_task, k8s_client):
    """
    dagster/app/tests/contract/task_resources_response.json is a sample response; Dagster's tests parse it into
    TaskResources. This test fails when the real response gains or loses a key, so the two sides move together.
    """
    dataset_task.spec.config = {}
    db.session.commit()

    body = create(client, system_headers, project, dataset_task).json()

    assert set(body) == set(json.loads(CONTRACT.read_text()))


def test_a_task_with_a_dataset_only_gets_no_configmap(client, system_headers, project, dataset_task, k8s_client):
    response = create(client, system_headers, project, dataset_task)

    assert response.json() == {"secret": f"task-{dataset_task.id}-{RUN_ID}", "config_map": None}
    k8s_client["create_namespaced_config_map_mock"].assert_not_called()


@pytest.mark.parametrize("config", [{"threshold": 3}, {}], ids=["config", "empty-config"])
def test_a_task_with_a_config_only_gets_no_secret(client, system_headers, project, config_task, k8s_client, config):
    config_task.spec.config = config
    db.session.commit()

    response = create(client, system_headers, project, config_task)

    assert response.json() == {"secret": None, "config_map": f"task-{config_task.id}-{RUN_ID}-config"}
    k8s_client["create_namespaced_secret_mock"].assert_not_called()
    assert k8s_client["create_namespaced_config_map_mock"].call_args.args[1].data == {"config.json": json.dumps(config)}


def test_a_task_with_neither_makes_nothing(client, system_headers, project, make_task, k8s_client):
    response = create(client, system_headers, project, make_task())

    assert response.json() == {"secret": None, "config_map": None}
    k8s_client["create_namespaced_secret_mock"].assert_not_called()
    k8s_client["create_namespaced_config_map_mock"].assert_not_called()


def test_a_run_that_has_its_objects_already_is_a_409_and_nothing_is_replaced(
        client, system_headers, project, dataset_task, k8s_client, run_resources_deletes):
    k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(status=409, reason="Conflict")

    response = create(client, system_headers, project, dataset_task)

    assert response.status_code == 409
    assert f"task-{dataset_task.id}-{RUN_ID}" in response.json()["error"]
    k8s_client["delete_namespaced_secret_mock"].assert_not_called()
    k8s_client["patch_namespaced_secret_mock"].assert_not_called()
    run_resources_deletes["secrets"].assert_not_called()


def test_any_other_cluster_error_is_not_hidden(client, system_headers, project, dataset_task, k8s_client):
    k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(status=403, reason="Forbidden")

    assert create(client, system_headers, project, dataset_task).status_code == 500


@pytest.mark.parametrize("run_id", ["Run_1", "run id", "-run", "r" * 64])
def test_a_run_id_that_cannot_be_a_name_or_a_label_value_is_a_400(
        client, system_headers, project, dataset_task, k8s_client, run_id):
    assert create(client, system_headers, project, dataset_task, run_id).status_code == 400
    k8s_client["create_namespaced_secret_mock"].assert_not_called()


def test_only_the_system_user_creates_them(client, admin_headers, project, dataset_task, k8s_client):
    assert create(client, admin_headers, project, dataset_task).status_code == 403
    k8s_client["create_namespaced_secret_mock"].assert_not_called()


def test_a_task_of_another_project_is_a_404(client, system_headers, other_project, dataset_task, k8s_client):
    assert create(client, system_headers, other_project, dataset_task).status_code == 404
    k8s_client["create_namespaced_secret_mock"].assert_not_called()


# --------------------------------------------------------------------------- delete


def patch(client, headers, project, task, body):
    return client.patch(f"/projects/{project.id}/tasks/{task.id}", json=body, headers=headers)


@pytest.mark.parametrize("status", ["SUCCESS", "FAILED", "CANCELED"])
def test_a_task_reaching_a_final_status_deletes_its_runs_secret_and_configmap_by_label(
        client, system_headers, project, make_task, run_resources_deletes, status):
    task = make_task()

    assert patch(client, system_headers, project, task, {"status": status, "executor_run_id": RUN_ID}).status_code == 200

    run_resources_deletes["secrets"].assert_called_once_with(NAMESPACE, label_selector=f"fn/run_id={RUN_ID}")
    run_resources_deletes["config_maps"].assert_called_once_with(NAMESPACE, label_selector=f"fn/run_id={RUN_ID}")


def test_the_run_id_is_the_one_the_task_already_has(client, system_headers, project, make_task, run_resources_deletes):
    task = make_task()
    patch(client, system_headers, project, task, {"status": "RUNNING", "executor_run_id": RUN_ID})
    run_resources_deletes["secrets"].assert_not_called()

    patch(client, system_headers, project, task, {"status": "SUCCESS"})

    run_resources_deletes["secrets"].assert_called_once_with(NAMESPACE, label_selector=f"fn/run_id={RUN_ID}")


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
def test_a_task_that_has_not_finished_keeps_them(client, system_headers, project, make_task, run_resources_deletes, status):
    task = make_task()

    assert patch(client, system_headers, project, task, {"status": status, "executor_run_id": RUN_ID}).status_code == 200

    run_resources_deletes["secrets"].assert_not_called()
    run_resources_deletes["config_maps"].assert_not_called()


def test_a_patch_that_leaves_the_status_alone_deletes_nothing(client, system_headers, project, make_task, run_resources_deletes):
    task = make_task(status="SUCCESS", executor_run_id=RUN_ID)

    assert patch(client, system_headers, project, task, {"exit_code": 0}).status_code == 200

    run_resources_deletes["secrets"].assert_not_called()


def test_a_task_that_never_ran_has_nothing_to_delete(client, system_headers, project, make_task, run_resources_deletes):
    task = make_task()

    assert patch(client, system_headers, project, task, {"status": "FAILED", "state_cause": "revoked"}).status_code == 200

    run_resources_deletes["secrets"].assert_not_called()
    run_resources_deletes["config_maps"].assert_not_called()


def test_a_failed_delete_leaves_the_task_as_it_was_so_the_next_patch_retries(
        client, system_headers, project, make_task, run_resources_deletes):
    task = make_task()
    run_resources_deletes["secrets"].side_effect = ApiException(status=500, reason="Server error")

    assert patch(client, system_headers, project, task, {"status": "FAILED", "executor_run_id": RUN_ID}).status_code == 500
    db.session.expire_all()
    assert Task.query.get(task.id).status == "PENDING"

    run_resources_deletes["secrets"].side_effect = None
    assert patch(client, system_headers, project, task, {"status": "FAILED", "executor_run_id": RUN_ID}).status_code == 200
    assert Task.query.get(task.id).status == "FAILED"
