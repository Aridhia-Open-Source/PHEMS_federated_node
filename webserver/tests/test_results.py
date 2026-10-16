from app.helpers.base_model import db


RESULTS_GLOBAL = "/global/repositories/results"


def results_link_url(project, repo):
    return f"/projects/{project.id}/repositories/results/{repo.id}"


def results_url(project):
    return f"/projects/{project.id}/results"


def test_create_global(client, admin_headers, global_secret):
    body = {"uri": "github.com/org/r2", "provider": "github", "secret_label": "test-creds"}

    response = client.post(RESULTS_GLOBAL, json=body, headers=admin_headers)
    assert response.status_code == 201
    assert response.json["uri"] == "github.com/org/r2"

    response = client.post(RESULTS_GLOBAL, json=body, headers=admin_headers)
    assert response.status_code == 409

    response = client.post(
        RESULTS_GLOBAL,
        json={"uri": "github.com/org/r3", "provider": "github", "secret_label": "test-creds", "target_dir": "x"},
        headers=admin_headers,
    )
    assert response.status_code == 400


def test_get_global_and_404(client, admin_headers, global_results_repo):
    response = client.get(f"{RESULTS_GLOBAL}/{global_results_repo.id}", headers=admin_headers)
    assert response.status_code == 200

    response = client.get(f"{RESULTS_GLOBAL}/999", headers=admin_headers)
    assert response.status_code == 404


def test_link_needs_lock(client, admin_headers, project, global_results_repo):
    response = client.put(
        results_link_url(project, global_results_repo), json={"target_dir": "results"}, headers=admin_headers
    )
    assert response.status_code == 409


def test_link_locked(client, admin_headers, lock_project, global_results_repo):
    url = results_link_url(lock_project, global_results_repo)

    response = client.put(url, json={"target_dir": "results"}, headers=admin_headers)
    assert response.status_code == 201

    response = client.put(url, json={"target_dir": "out"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["target_dir"] == "out"

    response = client.get(f"/projects/{lock_project.id}/repositories/results", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json) == 1


def test_second_results_repo_conflicts(client, admin_headers, lock_project, global_results_repo, make_results_repo):
    response = client.put(
        results_link_url(lock_project, global_results_repo), json={"target_dir": "results"}, headers=admin_headers
    )
    assert response.status_code == 201

    other = make_results_repo(uri="github.com/org/other")
    response = client.put(
        results_link_url(lock_project, other), json={"target_dir": "r"}, headers=admin_headers
    )
    assert response.status_code == 409


def test_link_into_watched_dir_refused(
    client, admin_headers, lock_project, global_trigger_repo, make_results_repo
):
    response = client.put(
        f"/projects/{lock_project.id}/repositories/triggers/{global_trigger_repo.id}",
        json={"watch_dir": "triggers"}, headers=admin_headers
    )
    assert response.status_code == 201

    loop = make_results_repo(uri="github.com/org/triggers")
    response = client.put(
        results_link_url(lock_project, loop), json={"target_dir": "triggers/out"}, headers=admin_headers
    )
    assert response.status_code == 400
    assert "overlap" in response.json["error"]


def test_post_result(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    task = make_task()
    body = {"task_id": task.id, "results_repository_id": global_results_repo.id}

    response = client.post(results_url(project), json=body, headers=admin_headers)
    assert response.status_code == 201
    assert response.json["step"] == "UNKNOWN"
    assert response.json["state"] == "IN_PROGRESS"
    assert response.json["results_repository_id"] == global_results_repo.id
    assert response.json["type"] == "PR"
    result_id = response.json["id"]

    response = client.post(results_url(project), json=body, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["id"] == result_id


def test_post_result_errors(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo, make_task
):
    task = make_task()
    valid = {"task_id": task.id, "results_repository_id": global_results_repo.id}

    response = client.post(results_url(project), json={**valid, "results_repository_id": 999}, headers=admin_headers)
    assert response.status_code == 400

    response = client.post(results_url(project), json={**valid, "task_id": 999}, headers=admin_headers)
    assert response.status_code == 404

    response = client.post(results_url(project), json={**valid, "task_id": "x"}, headers=admin_headers)
    assert response.status_code == 400

    response = client.post(results_url(other_project), json=valid, headers=admin_headers)
    assert response.status_code == 404


def test_patch_result(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    task = make_task()
    response = client.post(
        results_url(project),
        json={"task_id": task.id, "results_repository_id": global_results_repo.id},
        headers=admin_headers,
    )
    assert response.status_code == 201
    rid = response.json["id"]
    url = f"{results_url(project)}/{rid}"

    response = client.patch(url, json={"step": "OPENED", "number": 5, "url": "https://x/pull/5"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["step"] == "OPENED"
    assert response.json["number"] == 5

    response = client.patch(url, json={"step": "PUSHED"}, headers=admin_headers)
    assert response.status_code == 400

    response = client.patch(url, json={"bogus": 1}, headers=admin_headers)
    assert response.status_code == 400


def test_results_by_step_and_cross_project(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo, make_task
):
    task = make_task()
    response = client.post(
        results_url(project),
        json={"task_id": task.id, "results_repository_id": global_results_repo.id},
        headers=admin_headers,
    )
    assert response.status_code == 201
    rid = response.json["id"]

    response = client.patch(f"{results_url(project)}/{rid}", json={"step": "OPENED"}, headers=admin_headers)
    assert response.status_code == 200

    response = client.get(f"{results_url(project)}?step=OPENED", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json) == 1

    response = client.get(f"{results_url(project)}?step=PUSHED", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json) == 0

    response = client.get(f"{results_url(project)}?step=NOPE", headers=admin_headers)
    assert response.status_code == 400

    response = client.patch(
        f"/projects/{other_project.id}/results/{rid}", json={"step": "MERGED"}, headers=admin_headers
    )
    assert response.status_code == 404


def test_revoke_and_unlink_results_repo(client, admin_headers, project, global_results_repo, linked_results_repo):
    url = results_link_url(project, global_results_repo)

    response = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["active"] is False

    project.locked = True
    db.session.commit()

    response = client.delete(url, headers=admin_headers)
    assert response.status_code == 204
