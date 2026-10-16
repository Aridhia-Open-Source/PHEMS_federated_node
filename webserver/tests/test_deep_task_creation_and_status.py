"""
Deep tests: creating a task from a pull request, and the task status routes.

Where the app is unclear the test asserts the current behaviour and says so in a comment.
"""
import json

import pytest

from app.helpers.base_model import db
from app.models.task import Task

# --------------------------------------------------------------------------- helpers


def spec_body(spec) -> dict:
    return {"spec_raw": json.dumps({"spec": spec})}


def post_task(client, admin_headers, pr_url, spec_raw):
    return client.post(f"{pr_url}/task", json={"spec_raw": spec_raw}, headers=admin_headers)


def create_task(client, admin_headers, pr_url, spec_raw):
    response = post_task(client, admin_headers, pr_url, spec_raw)
    assert response.status_code == 201, response.json
    return response.json


def pr_state(client, admin_headers, pr_url) -> dict:
    response = client.get(pr_url, headers=admin_headers)
    assert response.status_code == 200
    return response.json


def link_url(project, repo) -> str:
    return f"/projects/{project.id}/repositories/triggers/{repo.id}"


# --------------------------------------------------------------------------- spec_raw variants


def test_minimal_spec_creates_task(client, admin_headers, project, pr_trigger):
    task = create_task(client, admin_headers, pr_trigger, json.dumps({"spec": {"image": "img:1"}}))
    assert task["status"] == "PENDING"
    assert task["spec"]["image"] == "img:1"
    assert task["spec"]["dataset_id"] is None  # project has no dataset
    assert task["project_id"] == project.id


def test_spec_with_env_and_params_is_kept(client, admin_headers, pr_trigger):
    spec = {"image": "img:2", "env": {"MY_VAR": "x"}, "params": {"p": 1}}
    task = create_task(client, admin_headers, pr_trigger, json.dumps({"spec": spec}))
    assert task["spec"]["env"] == {"MY_VAR": "x"}
    assert Task.query.get(task["id"]).params == {"p": 1}


def test_spec_name_overrides_default_pr_name(client, admin_headers, pr_trigger):
    task = create_task(client, admin_headers, pr_trigger, json.dumps({"spec": {"image": "i:1", "name": "MyTask"}}))
    assert task["name"] == "MyTask"


def test_spec_accepts_docker_image_alias(client, admin_headers, pr_trigger):
    task = create_task(client, admin_headers, pr_trigger, json.dumps({"spec": {"docker_image": "img:9"}}))
    assert task["spec"]["image"] == "img:9"


def test_extra_top_level_keys_next_to_spec_are_tolerated(client, admin_headers, pr_trigger):
    # The PR file is user authored; only the "spec" key is read (current behaviour).
    raw = json.dumps({"description": "hi", "spec": {"image": "img:1"}})
    assert post_task(client, admin_headers, pr_trigger, raw).status_code == 201


def test_unknown_spec_field_rejects_pr(client, admin_headers, pr_trigger):
    response = post_task(client, admin_headers, pr_trigger, json.dumps({"spec": {"image": "i:1", "bogus": 1}}))
    assert response.status_code == 400
    pr = pr_state(client, admin_headers, pr_trigger)
    assert pr["state"] == "REJECTED"
    assert pr["task_id"] is None


@pytest.mark.parametrize("spec", [
    {},                                    # missing image
    {"env": {"A": "b"}},                   # missing image, others present
    {"image": 5},                          # wrong type
    {"image": None},
    {"image": "i:1", "env": "notadict"},
    {"image": "i:1", "params": [1, 2]},
    {"image": "i:1", "dataset": 3},
    {"image": "x" * 5000},                 # image too long
    {"image": "i:1", "env": {"bad key!": "v"}},
])
def test_invalid_spec_rejects_pr(client, admin_headers, pr_trigger, spec):
    response = post_task(client, admin_headers, pr_trigger, json.dumps({"spec": spec}))
    assert response.status_code == 400
    pr = pr_state(client, admin_headers, pr_trigger)
    assert pr["state"] == "REJECTED"
    assert pr["state_cause"]


@pytest.mark.parametrize("raw", [
    "not json at all",
    "",
    "[]",
    "null",
    '"a string"',
    '{"spec": "a string"}',
    '{"spec": [1, 2]}',
    '{"spec": null}',
    '{"nospec": {"image": "i:1"}}',
])
def test_unparsable_or_wrong_shape_spec_raw_is_400_and_rejects(client, admin_headers, pr_trigger, raw):
    response = post_task(client, admin_headers, pr_trigger, raw)
    assert response.status_code == 400, response.json
    assert "error" in response.json
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "REJECTED"


@pytest.mark.parametrize("body", [{}, {"spec_raw": None}, {"spec_raw": 5}, {"spec_raw": {"spec": {"image": "i"}}}])
def test_spec_raw_must_be_a_string(client, admin_headers, pr_trigger, body):
    response = client.post(f"{pr_trigger}/task", json=body, headers=admin_headers)
    assert response.status_code == 400
    # Nothing was parsed, so the PR is not judged
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "UNKNOWN"


def test_huge_spec_raw_is_rejected(client, admin_headers, pr_trigger):
    raw = json.dumps({"spec": {"image": "i:1", "params": {"blob": "x" * (70 * 1024)}}})
    response = post_task(client, admin_headers, pr_trigger, raw)
    assert response.status_code in (400, 413)
    pr = pr_state(client, admin_headers, pr_trigger)
    assert pr["state"] != "YIELDED"
    assert pr["task_id"] is None


def test_deeply_nested_params_are_accepted_and_stored(client, admin_headers, pr_trigger):
    params = {"a": {"b": {"c": {"d": [1, {"e": "f"}]}}}}
    task = create_task(client, admin_headers, pr_trigger, json.dumps({"spec": {"image": "i:1", "params": params}}))
    assert Task.query.get(task["id"]).params == params


def test_deeply_nested_json_bomb_does_not_500(client, admin_headers, pr_trigger):
    raw = "[" * 100000 + "]" * 100000
    response = post_task(client, admin_headers, pr_trigger, raw)
    assert response.status_code == 400


# --------------------------------------------------------------------------- datasets


def test_project_without_dataset_gets_none(client, admin_headers, pr_trigger, spec_raw):
    assert create_task(client, admin_headers, pr_trigger, spec_raw)["spec"]["dataset_id"] is None


def test_default_dataset_is_used(client, admin_headers, linked_dataset, global_dataset, pr_trigger, spec_raw):
    assert create_task(client, admin_headers, pr_trigger, spec_raw)["spec"]["dataset_id"] == global_dataset.id


def test_dataset_override_picks_named_dataset(
    client, admin_headers, project, linked_dataset, global_dataset, make_global_dataset, pr_trigger
):
    second = make_global_dataset(name="Second")
    put = client.put(f"/projects/{project.id}/datasets/{second.id}", json={}, headers=admin_headers)
    assert put.status_code == 201
    raw = json.dumps({"spec": {"image": "i:1", "dataset": "second"}})
    assert create_task(client, admin_headers, pr_trigger, raw)["spec"]["dataset_id"] == second.id


def test_dataset_override_name_is_case_insensitive(
    client, admin_headers, linked_dataset, global_dataset, pr_trigger
):
    raw = json.dumps({"spec": {"image": "i:1", "dataset": global_dataset.name.upper()}})
    assert create_task(client, admin_headers, pr_trigger, raw)["spec"]["dataset_id"] == global_dataset.id


def test_nonexistent_dataset_override_rejects_pr(client, admin_headers, linked_dataset, pr_trigger):
    raw = json.dumps({"spec": {"image": "i:1", "dataset": "does-not-exist"}})
    response = post_task(client, admin_headers, pr_trigger, raw)
    assert response.status_code == 400
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "REJECTED"


def test_unlinked_dataset_override_rejects_pr(client, admin_headers, make_global_dataset, pr_trigger):
    make_global_dataset(name="elsewhere")  # exists globally, never linked to the project
    raw = json.dumps({"spec": {"image": "i:1", "dataset": "elsewhere"}})
    response = post_task(client, admin_headers, pr_trigger, raw)
    assert response.status_code == 400
    pr = pr_state(client, admin_headers, pr_trigger)
    assert pr["state"] == "REJECTED"
    assert "elsewhere" in pr["state_cause"]


def test_globally_disabled_dataset_is_refused(client, admin_headers, linked_dataset, global_dataset, pr_trigger, spec_raw):
    global_dataset.enabled = False
    db.session.commit()
    response = post_task(client, admin_headers, pr_trigger, spec_raw)
    assert response.status_code == 400
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "REJECTED"


def test_revoked_dataset_link_is_refused(
    client, admin_headers, project, linked_dataset, global_dataset, pr_trigger, spec_raw
):
    revoke = client.patch(
        f"/projects/{project.id}/datasets/{global_dataset.id}", json={"revoked": True}, headers=admin_headers
    )
    assert revoke.status_code == 200
    assert post_task(client, admin_headers, pr_trigger, spec_raw).status_code == 400


# --------------------------------------------------------------------------- idempotency and PR states


def test_second_post_returns_same_task_even_with_different_spec(client, admin_headers, pr_trigger, spec_raw):
    first = create_task(client, admin_headers, pr_trigger, spec_raw)
    again = post_task(client, admin_headers, pr_trigger, json.dumps({"spec": {"image": "other:2"}}))
    assert again.status_code == 200
    assert again.json["id"] == first["id"]
    assert again.json["spec"]["image"] == "img:1"
    listing = client.get("/tasks", headers=admin_headers)
    assert listing.json["total"] == 1


def test_second_post_with_garbage_body_is_still_200(client, admin_headers, pr_trigger, spec_raw):
    first = create_task(client, admin_headers, pr_trigger, spec_raw)
    again = client.post(f"{pr_trigger}/task", json={}, headers=admin_headers)
    assert again.status_code == 200
    assert again.json["id"] == first["id"]


@pytest.mark.parametrize("state, cause", [("REJECTED", "bad spec")])
def test_rejected_pr_cannot_create_task(client, admin_headers, pr_trigger, spec_raw, state, cause):
    patch = client.patch(pr_trigger, json={"state": state, "state_cause": cause}, headers=admin_headers)
    assert patch.status_code == 200
    response = post_task(client, admin_headers, pr_trigger, spec_raw)
    assert response.status_code == 409
    assert pr_state(client, admin_headers, pr_trigger)["state"] == state


def test_yielded_pr_without_task_state_is_consistent_after_create(client, admin_headers, pr_trigger, spec_raw):
    task = create_task(client, admin_headers, pr_trigger, spec_raw)
    pr = pr_state(client, admin_headers, pr_trigger)
    assert pr["state"] == "YIELDED"
    assert pr["task_id"] == task["id"]
    assert pr["state_cause"] is None


def test_unknown_pr_number_and_unlinked_project_are_404(
    client, admin_headers, project, other_project, global_trigger_repo, pr_trigger, spec_raw
):
    base = link_url(project, global_trigger_repo)
    assert post_task(client, admin_headers, f"{base}/pull_requests/99", spec_raw).status_code == 404
    other = f"{link_url(other_project, global_trigger_repo)}/pull_requests/1"
    assert post_task(client, admin_headers, other, spec_raw).status_code == 404


def test_revoked_link_cannot_create_task(client, admin_headers, project, global_trigger_repo, pr_trigger, spec_raw):
    revoke = client.patch(link_url(project, global_trigger_repo), json={"revoked": True}, headers=admin_headers)
    assert revoke.status_code == 200
    response = post_task(client, admin_headers, pr_trigger, spec_raw)
    assert response.status_code == 409


def test_disabled_link_cannot_create_task(client, admin_headers, project, global_trigger_repo, pr_trigger, spec_raw):
    project.locked = True
    db.session.commit()
    disable = client.patch(link_url(project, global_trigger_repo), json={"enabled": False}, headers=admin_headers)
    assert disable.status_code == 200
    response = post_task(client, admin_headers, pr_trigger, spec_raw)
    assert response.status_code == 409


def test_locked_project_create_task_current_behaviour(client, admin_headers, project, pr_trigger, spec_raw):
    # Unsure what the ADR wants for a locked project; this asserts the current behaviour (201).
    project.locked = True
    db.session.commit()
    assert post_task(client, admin_headers, pr_trigger, spec_raw).status_code == 201


# --------------------------------------------------------------------------- status transitions


@pytest.fixture
def tid(client, admin_headers, pr_trigger, spec_raw) -> int:
    return create_task(client, admin_headers, pr_trigger, spec_raw)["id"]


def patch_task(client, admin_headers, task_id, body):
    return client.patch(f"/tasks/{task_id}", json=body, headers=admin_headers)


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING", "SUCCESS", "FAILED", "CANCELED"])
def test_legal_statuses_from_pending(client, admin_headers, tid, status):
    response = patch_task(client, admin_headers, tid, {"status": status})
    assert response.status_code == 200
    assert response.json["status"] == status
    assert client.get(f"/tasks/{tid}", headers=admin_headers).json["status"] == status


def test_normal_lifecycle_pending_to_success(client, admin_headers, tid):
    for status in ("QUEUED", "RUNNING", "SUCCESS"):
        assert patch_task(client, admin_headers, tid, {"status": status}).json["status"] == status


@pytest.mark.parametrize("status", ["bogus", "running", "", None, 5, ["RUNNING"], "DONE"])
def test_illegal_status_values_are_400(client, admin_headers, tid, status):
    assert patch_task(client, admin_headers, tid, {"status": status}).status_code == 400
    assert client.get(f"/tasks/{tid}", headers=admin_headers).json["status"] == "PENDING"


@pytest.mark.parametrize("terminal", ["SUCCESS", "FAILED", "CANCELED"])
def test_terminal_status_is_final(client, admin_headers, tid, terminal):
    assert patch_task(client, admin_headers, tid, {"status": terminal}).status_code == 200
    response = patch_task(client, admin_headers, tid, {"status": "RUNNING"})
    assert response.status_code == 409
    assert client.get(f"/tasks/{tid}", headers=admin_headers).json["status"] == terminal


@pytest.mark.parametrize("terminal", ["SUCCESS", "FAILED", "CANCELED"])
def test_same_terminal_status_again_is_200(client, admin_headers, tid, terminal):
    assert patch_task(client, admin_headers, tid, {"status": terminal}).status_code == 200
    again = patch_task(client, admin_headers, tid, {"status": terminal})
    assert again.status_code == 200 and again.json["status"] == terminal


def test_retry_failed_task_resets_to_pending(client, admin_headers, tid):
    assert patch_task(client, admin_headers, tid, {"status": "FAILED"}).status_code == 200
    assert client.post(f"/tasks/{tid}/retry", headers=admin_headers).status_code in (200, 201)
    assert client.get(f"/tasks/{tid}", headers=admin_headers).json["status"] == "PENDING"


def test_dagster_run_id_roundtrip_and_type_check(client, admin_headers, tid):
    ok = patch_task(client, admin_headers, tid, {"dagster_run_id": "run-42"})
    assert ok.status_code == 200
    assert client.get(f"/tasks/{tid}", headers=admin_headers).json["dagster_run_id"] == "run-42"
    for bad in (42, None, ["x"], {"a": 1}):
        assert patch_task(client, admin_headers, tid, {"dagster_run_id": bad}).status_code == 400


def test_patch_with_unknown_field_is_400_and_applies_nothing(client, admin_headers, tid):
    response = patch_task(client, admin_headers, tid, {"status": "RUNNING", "bogus": 1})
    assert response.status_code == 400
    assert "bogus" in response.json["error"]
    assert client.get(f"/tasks/{tid}", headers=admin_headers).json["status"] == "PENDING"


@pytest.mark.parametrize("field", ["name", "project_id", "spec", "id", "requested_by", "created_at"])
def test_immutable_fields_cannot_be_patched(client, admin_headers, tid, field):
    assert patch_task(client, admin_headers, tid, {field: "x"}).status_code == 400


def test_patch_empty_body_is_400(client, admin_headers, tid):
    assert patch_task(client, admin_headers, tid, {}).status_code == 400


def test_patch_unknown_task_is_404(client, admin_headers):
    assert patch_task(client, admin_headers, 999, {"status": "RUNNING"}).status_code == 404


def test_patch_exit_code_and_state_cause(client, admin_headers, tid):
    response = patch_task(client, admin_headers, tid, {"status": "FAILED", "exit_code": 137, "state_cause": "oom"})
    assert response.status_code == 200
    assert response.json["exit_code"] == 137
    assert response.json["state_cause"] == "oom"
    assert patch_task(client, admin_headers, tid, {"exit_code": True}).status_code == 400


def test_failed_task_can_be_retried_and_resets(client, admin_headers, tid):
    patch_task(client, admin_headers, tid, {"status": "FAILED", "dagster_run_id": "r", "exit_code": 1})
    retry = client.post(f"/tasks/{tid}/retry", json={}, headers=admin_headers)
    assert retry.status_code == 200
    assert retry.json["status"] == "PENDING"
    assert retry.json["dagster_run_id"] is None
    assert retry.json["exit_code"] is None
    # a task that is not failed/canceled cannot be retried
    assert client.post(f"/tasks/{tid}/retry", json={}, headers=admin_headers).status_code == 400


# --------------------------------------------------------------------------- listing, filters, pagination


def test_list_filter_by_status(client, admin_headers, make_task):
    make_task(status="RUNNING")
    make_task(status="RUNNING")
    make_task(status="FAILED")
    make_task()
    running = client.get("/tasks?status=RUNNING", headers=admin_headers)
    assert running.status_code == 200
    assert running.json["total"] == 2
    assert {t["status"] for t in running.json["tasks"]} == {"RUNNING"}
    assert client.get("/tasks?status=SUCCESS", headers=admin_headers).json["total"] == 0
    assert client.get("/tasks", headers=admin_headers).json["total"] == 4


@pytest.mark.parametrize("status", ["bogus", "running", ""])
def test_list_invalid_status_filter_is_400(client, admin_headers, status):
    assert client.get(f"/tasks?status={status}", headers=admin_headers).status_code == 400


def test_list_filter_by_project_and_combined(client, admin_headers, project, other_project, make_task):
    make_task(status="RUNNING")
    make_task()
    other = make_task(project=other_project, status="RUNNING")
    mine = client.get(f"/tasks?project_id={project.id}", headers=admin_headers)
    assert mine.json["total"] == 2
    assert all(t["project_id"] == project.id for t in mine.json["tasks"])
    both = client.get(f"/tasks?project_id={other_project.id}&status=RUNNING", headers=admin_headers)
    assert [t["id"] for t in both.json["tasks"]] == [other.id]
    assert client.get(f"/tasks?project_id={project.id}&status=SUCCESS", headers=admin_headers).json["total"] == 0
    assert client.get("/tasks?project_id=9999", headers=admin_headers).json["total"] == 0


def test_list_pagination(client, admin_headers, make_task):
    ids = [make_task().id for _ in range(5)]
    first = client.get("/tasks?page=1&per_page=2", headers=admin_headers).json
    assert [t["id"] for t in first["tasks"]] == ids[:2]
    assert (first["total"], first["pages"], first["page"], first["per_page"]) == (5, 3, 1, 2)
    last = client.get("/tasks?page=3&per_page=2", headers=admin_headers).json
    assert [t["id"] for t in last["tasks"]] == ids[4:]


def test_list_pagination_past_the_end(client, admin_headers, make_task):
    make_task()
    response = client.get("/tasks?page=5&per_page=2", headers=admin_headers)
    # Current behaviour is asserted loosely: either an empty page or a 404, never a 500.
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert response.json["tasks"] == []


@pytest.mark.parametrize("query", ["page=abc", "per_page=xyz", "project_id=abc"])
def test_list_bad_pagination_args_are_client_errors(client, admin_headers, make_task, query):
    make_task()
    assert 400 <= client.get(f"/tasks?{query}", headers=admin_headers).status_code < 500


@pytest.mark.parametrize("query", ["page=0", "per_page=-1"])
def test_list_pagination_below_one_is_clamped(client, admin_headers, make_task, query):
    make_task()
    assert client.get(f"/tasks?{query}", headers=admin_headers).status_code == 200


def test_get_task_shape_and_404(client, admin_headers, tid):
    one = client.get(f"/tasks/{tid}", headers=admin_headers)
    assert one.status_code == 200
    assert {"id", "name", "status", "spec", "project_id"} <= set(one.json)
    assert client.get("/tasks/999999", headers=admin_headers).status_code == 404


# --------------------------------------------------------------------------- results and delete


def test_task_results_empty_then_listed(client, admin_headers, tid):
    assert client.get(f"/tasks/{tid}/results", headers=admin_headers).json == []
    assert client.get("/tasks/999/results", headers=admin_headers).status_code == 404


def test_task_results_lists_delivery(client, admin_headers, project, linked_results_repo, global_results_repo, make_task):
    task = make_task()
    assert client.patch(f"/tasks/{task.id}", json={"status": "SUCCESS"}, headers=admin_headers).status_code == 200
    posted = client.post(
        f"/projects/{project.id}/results",
        json={"task_id": task.id, "results_repository_id": global_results_repo.id}, headers=admin_headers,
    )
    assert posted.status_code == 201
    results = client.get(f"/tasks/{task.id}/results", headers=admin_headers)
    assert results.status_code == 200
    assert [r["id"] for r in results.json] == [posted.json["id"]]


def test_task_deletion_is_not_supported(client, admin_headers, tid):
    # No DELETE route exists for tasks; the task must survive the attempt.
    response = client.delete(f"/tasks/{tid}", headers=admin_headers)
    assert response.status_code in (404, 405, 501)
    assert client.get(f"/tasks/{tid}", headers=admin_headers).status_code == 200
