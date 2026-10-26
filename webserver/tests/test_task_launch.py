"""
POST /projects/<id>/tasks/<id>/launch, the launcher's one call: the decision (helpers/task_config.decide_launch, whose
rules test_task_config.py covers), the FAILED move on "fail", the run inputs on "launch", and a repeat being safe.
"""
import json
from pathlib import Path

import pytest

from app.helpers.base_model import db
from app.helpers.const import TASK_CAUSE_MAX_LENGTH
from app.models.task import Task

# Fixtures the module shares with test_task_config.py
from tests.test_task_config import (  # noqa: F401
    full_task, resources, patch, pinned_task, reload_task, set_target_dir,
)

CONTRACT = Path(__file__).resolve().parents[2] / "dagster" / "app" / "tests" / "contract" / "launch_response.json"


def launch_url(project, task) -> str:
    return f"/projects/{project.id}/tasks/{task.id}/launch"


def launch(client, headers, project, task):
    return client.post(launch_url(project, task), headers=headers)


def stored(task_id) -> tuple:
    db.session.expire_all()
    task = reload_task(task_id)
    return task.status, task.state_cause, task.attempt


def shape(value):
    """The keys of a JSON value, recursively: what a consumer's model is written against."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    return None


# --------------------------------------------------------------------------- launch


def test_launch_returns_the_run_inputs_and_changes_nothing(client, admin_headers, system_headers, project, full_task, global_dataset):
    before = stored(full_task.id)
    response = launch(client, system_headers, project, full_task)

    assert response.status_code == 200, response.json
    body = response.json
    assert (body["outcome"], body["cause"]) == ("launch", None)
    assert body["task"]["id"] == full_task.id and body["task"]["status"] == "PENDING"
    assert body["task"]["spec"] == {"image": full_task.spec.image, "dataset_id": global_dataset.id, "env": full_task.spec.env}
    assert body["task"]["attempt"] == full_task.attempt
    # the dataset as the project-dataset GET returns it, secret reference included
    resource = client.get(f"/projects/{project.id}/datasets/{global_dataset.id}", headers=admin_headers).json
    assert body["dataset"] == resource["dataset"]
    assert {"provider", "key", "namespace"} <= set(body["dataset"]["secret"])
    assert stored(full_task.id) == before


def test_launch_of_a_task_without_a_dataset_has_none(client, system_headers, project, make_task):
    task = make_task()
    body = launch(client, system_headers, project, task).json
    assert (body["outcome"], body["dataset"]) == ("launch", None)
    assert body["task"]["spec"]["dataset_id"] is None


def test_launch_is_safe_to_repeat(client, system_headers, project, full_task):
    first = launch(client, system_headers, project, full_task).json
    second = launch(client, system_headers, project, full_task).json
    assert first == second and stored(full_task.id)[0] == "PENDING"


# --------------------------------------------------------------------------- fail


def fail_revoked(client, admin_headers, resources, **_):
    patch(client, admin_headers, resources["dataset"][0], revoked=True)
    return f"revoked: {resources['dataset'][1]}"


def fail_changed(client, admin_headers, project, global_results_repo, **_):
    set_target_dir(client, admin_headers, project, global_results_repo, "out")
    return "task configuration changed since the task was created: results.target_dir: 'results' -> 'out'"


def fail_inactive(client, admin_headers, project, resources, global_dataset, **_):
    patch(client, admin_headers, resources["dataset"][0], enabled=False)
    return f"Dataset {global_dataset.name} is not active in project {project.name}"


def fail_secret(global_dataset, **_):
    global_dataset.secret.enabled = False
    db.session.commit()
    return f"The secret of dataset {global_dataset.name} is disabled"


@pytest.mark.parametrize("cause_of", [fail_revoked, fail_changed, fail_inactive, fail_secret],
                         ids=["revoked", "changed", "not-active", "secret-disabled"])
def test_each_cause_fails_the_task_with_it_and_a_repeat_changes_nothing(
        client, admin_headers, system_headers, project, full_task, resources, global_dataset, global_results_repo, cause_of):
    cause = cause_of(client=client, admin_headers=admin_headers, project=project, resources=resources,
                     global_dataset=global_dataset, global_results_repo=global_results_repo)

    response = launch(client, system_headers, project, full_task)

    assert response.status_code == 200, response.json
    assert (response.json["outcome"], response.json["cause"]) == ("fail", cause)
    assert response.json["task"]["status"] == "FAILED" and response.json["dataset"] is None
    assert stored(full_task.id) == ("FAILED", cause, full_task.attempt)

    again = launch(client, system_headers, project, full_task)
    assert again.status_code == 409, again.json
    assert stored(full_task.id) == ("FAILED", cause, full_task.attempt)


def test_the_decision_in_config_and_in_launch_agree(client, admin_headers, system_headers, project, full_task, resources):
    patch(client, admin_headers, resources["dataset"][0], revoked=True)
    decided = client.get(f"/projects/{project.id}/tasks/{full_task.id}/config", headers=admin_headers).json
    launched = launch(client, system_headers, project, full_task).json
    assert (decided["outcome"], decided["cause"]) == (launched["outcome"], launched["cause"])


def test_a_long_cause_is_cut_to_the_launchers_length(client, system_headers, project, full_task, monkeypatch):
    from app.helpers.task_config import LaunchDecision
    monkeypatch.setattr("app.tasks_api.decide_launch", lambda task: LaunchDecision("fail", "revoked: " + "x" * 2000, [], []))

    body = launch(client, system_headers, project, full_task).json

    assert body["outcome"] == "fail" and len(body["cause"]) == TASK_CAUSE_MAX_LENGTH == 1024
    assert stored(full_task.id)[1] == body["cause"]


# --------------------------------------------------------------------------- not pending


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING", "SUCCESS", "FAILED", "CANCELED"])
def test_a_task_not_pending_is_a_409_and_is_left_alone(client, system_headers, project, make_task, status):
    task = make_task(status=status, state_cause="kept")

    response = launch(client, system_headers, project, task)

    assert response.status_code == 409
    assert status in response.json["error"]
    assert stored(task.id) == (status, "kept", task.attempt)


def test_a_task_of_another_project_is_a_404(client, system_headers, other_project, make_task):
    task = make_task()
    assert launch(client, system_headers, other_project, task).status_code == 404
    assert client.post(f"/projects/{task.project_id}/tasks/9999/launch", headers=system_headers).status_code == 404


# --------------------------------------------------------------------------- permissions


def test_the_system_user_may_launch_and_fail(client, system_headers, admin_headers, project, full_task, resources):
    assert launch(client, system_headers, project, full_task).json["outcome"] == "launch"
    patch(client, admin_headers, resources["dataset"][0], revoked=True)
    response = launch(client, system_headers, project, full_task)
    assert response.status_code == 200 and response.json["outcome"] == "fail"
    assert stored(full_task.id)[0] == "FAILED"


def test_a_caller_without_the_scope_is_refused_and_nothing_changes(
        client, mock_kc_client, post_json_user_header, admin_headers, system_headers, project, full_task, resources):
    """The scope is PATCH task's (can_admin_dataset); Keycloak refuses a caller whose roles lack it."""
    patch(client, admin_headers, resources["dataset"][0], revoked=True)
    before = stored(full_task.id)
    keycloak = mock_kc_client["wrappers_kc"].return_value
    keycloak.is_token_valid.side_effect = lambda token, scope, *a, **k: token in ("admin_token", "system_token")

    assert launch(client, post_json_user_header, project, full_task).status_code == 403
    assert stored(full_task.id) == before
    assert launch(client, system_headers, project, full_task).status_code == 200


def test_no_token_is_refused(client, project, full_task):
    assert client.post(launch_url(project, full_task)).status_code in (401, 403)


# --------------------------------------------------------------------------- contract with Dagster


@pytest.mark.skipif(not CONTRACT.is_file(), reason="the Dagster source is not next to webserver/")
@pytest.mark.parametrize("with_dataset", [True, False])
def test_the_response_has_the_shape_dagsters_launch_decision_parses(
        client, system_headers, project, full_task, make_task, with_dataset):
    """
    dagster/app/tests/contract/launch_response.json is a sample "launch" response; Dagster's tests parse it into
    LaunchDecision. This test fails when the real response gains or loses a key, so the two sides move together.
    """
    task = full_task if with_dataset else make_task()
    body = launch(client, system_headers, project, task).json
    sample = json.loads(CONTRACT.read_text())
    expected = shape(sample)
    if not with_dataset:
        assert body["dataset"] is None
        body = {**body, "dataset": sample["dataset"]}
    assert shape(body) == expected
