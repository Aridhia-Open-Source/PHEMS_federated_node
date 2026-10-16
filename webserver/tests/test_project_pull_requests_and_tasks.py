def test_list_and_get_pr(client, admin_headers, project, global_trigger_repo, pr_trigger):
    list_url = f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}/pull_requests"

    listing = client.get(list_url, headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json["total"] == 1
    assert listing.json["items"][0]["number"] == 1

    response = client.get(pr_trigger, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["state"] == "UNKNOWN"
    assert response.json["task_id"] is None


def test_list_filter_by_state(client, admin_headers, project, global_trigger_repo, pr_trigger, ingest_prs):
    list_url = f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}/pull_requests"
    ingest_prs(global_trigger_repo.id, 2, base_branch="dev")

    ignored = client.get(f"{list_url}?state=IGNORED", headers=admin_headers)
    assert ignored.status_code == 200
    assert ignored.json["total"] == 1
    assert ignored.json["items"][0]["number"] == 2

    invalid = client.get(f"{list_url}?state=NOPE", headers=admin_headers)
    assert invalid.status_code == 400


def test_get_unknown_pr(client, admin_headers, project, global_trigger_repo, pr_trigger):
    list_url = f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}/pull_requests"

    response = client.get(f"{list_url}/99", headers=admin_headers)
    assert response.status_code == 404


def test_patch_state(client, admin_headers, pr_trigger):
    response = client.patch(pr_trigger, json={"state": "REJECTED", "state_cause": "bad"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["state"] == "REJECTED"
    assert response.json["state_cause"] == "bad"


def test_patch_bad_state(client, admin_headers, pr_trigger):
    bogus = client.patch(pr_trigger, json={"state": "BOGUS"}, headers=admin_headers)
    assert bogus.status_code == 400

    no_cause = client.patch(pr_trigger, json={"state": "REJECTED"}, headers=admin_headers)
    assert no_cause.status_code == 400


def test_create_task(client, admin_headers, project, pr_trigger, spec_raw):
    response = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json["status"] == "PENDING"
    assert response.json["spec"]["image"] == "img:1"
    assert response.json["project_id"] == project.id
    assert response.json["name"] == "PR 1"
    tid = response.json["id"]

    pr = client.get(pr_trigger, headers=admin_headers)
    assert pr.status_code == 200
    assert pr.json["state"] == "YIELDED"
    assert pr.json["task_id"] == tid


def test_create_task_is_idempotent(client, admin_headers, pr_trigger, spec_raw):
    first = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert first.status_code == 201

    again = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert again.status_code == 200
    assert again.json["id"] == first.json["id"]


def test_task_gets_default_dataset(client, admin_headers, linked_dataset, global_dataset, pr_trigger, spec_raw):
    response = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json["spec"]["dataset_id"] == global_dataset.id


def test_bad_spec_rejects_pr(client, admin_headers, pr_trigger):
    response = client.post(f"{pr_trigger}/task", json={"spec_raw": "{}"}, headers=admin_headers)
    assert response.status_code == 400

    pr = client.get(pr_trigger, headers=admin_headers)
    assert pr.status_code == 200
    assert pr.json["state"] == "REJECTED"
    assert "spec" in pr.json["state_cause"]


def test_missing_spec_raw(client, admin_headers, pr_trigger):
    response = client.post(f"{pr_trigger}/task", json={}, headers=admin_headers)
    assert response.status_code == 400


def test_tasks_routes(client, admin_headers, project, pr_trigger, spec_raw):
    created = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert created.status_code == 201
    tid = created.json["id"]

    listing = client.get(f"/tasks?project_id={project.id}", headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json["total"] == 1
    assert listing.json["tasks"][0]["id"] == tid

    one = client.get(f"/tasks/{tid}", headers=admin_headers)
    assert one.status_code == 200

    missing = client.get("/tasks/999", headers=admin_headers)
    assert missing.status_code == 404


def test_patch_task(client, admin_headers, pr_trigger, spec_raw):
    created = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert created.status_code == 201
    tid = created.json["id"]

    patched = client.patch(
        f"/tasks/{tid}", json={"status": "RUNNING", "dagster_run_id": "run-1"}, headers=admin_headers
    )
    assert patched.status_code == 200
    assert patched.json["status"] == "RUNNING"
    assert patched.json["dagster_run_id"] == "run-1"

    bogus = client.patch(f"/tasks/{tid}", json={"bogus": 1}, headers=admin_headers)
    assert bogus.status_code == 400

    results = client.get(f"/tasks/{tid}/results", headers=admin_headers)
    assert results.status_code == 200
    assert results.json == []
