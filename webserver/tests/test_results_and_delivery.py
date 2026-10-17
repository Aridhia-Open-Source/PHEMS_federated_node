"""
Results repositories (link rules, target_dir) and PR results (creation, step/state, filters), ADR 0019 sections 8 and 11.
One test per rule; fixtures come from conftest.
"""
import pytest

from app.helpers.base_model import db

RESULTS_GLOBAL = "/global/repositories/results"


def link_url(project, repo):
    return f"/projects/{project.id}/repositories/results/{repo.id}"


def trigger_url(project, repo):
    return f"/projects/{project.id}/repositories/triggers/{repo.id}"


def results_url(project):
    return f"/projects/{project.id}/results"


def links(client, admin_headers, project):
    return client.get(f"/projects/{project.id}/repositories/results", headers=admin_headers).json


def set_locked(project, locked=True):
    project.locked = locked
    db.session.commit()


def put_link(client, admin_headers, project, repo, target_dir="results"):
    """Link a results repository (PUT needs the project locked); returns the response, project left unlocked."""
    set_locked(project, True)
    response = client.put(link_url(project, repo), json={"target_dir": target_dir}, headers=admin_headers)
    set_locked(project, False)
    return response


def post_result(client, admin_headers, project, task, repo):
    return client.post(results_url(project), json={"task_id": task.id, "results_repository_id": repo.id},
                       headers=admin_headers)


def new_result(client, admin_headers, project, task, repo):
    """A result can only be posted for a SUCCESS task: finish it first."""
    assert client.patch(f"/projects/{project.id}/tasks/{task.id}", json={"status": "SUCCESS"}, headers=admin_headers).status_code == 200
    response = post_result(client, admin_headers, project, task, repo)
    assert response.status_code == 201, response.json
    return response.json["id"]


def patch_result(client, admin_headers, project, rid, body):
    return client.patch(f"{results_url(project)}/{rid}", json=body, headers=admin_headers)


def get_result(client, admin_headers, project, rid):
    return client.get(f"{results_url(project)}/{rid}", headers=admin_headers).json


@pytest.fixture
def result_id(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    """A result (step UNKNOWN, state IN_PROGRESS) of a fresh task, on the linked repository."""
    return new_result(client, admin_headers, project, make_task(), global_results_repo)


# ---------------------------------------------------------------- global results repository


def test_global_results_repo_create_get(client, admin_headers, global_secret, global_results_repo, git_provider):
    body = {"provider_id": git_provider.id, "repo_path": "org/r2", "secret_label": "test-creds"}
    assert client.post(RESULTS_GLOBAL, json=body, headers=admin_headers).status_code == 201
    assert client.post(RESULTS_GLOBAL, json=body, headers=admin_headers).status_code == 409
    # target_dir belongs to the link, not the global repository
    assert client.post(RESULTS_GLOBAL, json={**body, "repo_path": "org/r3", "target_dir": "x"},
                       headers=admin_headers).status_code == 400
    assert client.get(f"{RESULTS_GLOBAL}/{global_results_repo.id}", headers=admin_headers).status_code == 200
    assert client.get(f"{RESULTS_GLOBAL}/999", headers=admin_headers).status_code == 404


# ---------------------------------------------------------------- link rules


def test_link_needs_lock_then_relink_replaces_settings(client, admin_headers, project, global_results_repo):
    url = link_url(project, global_results_repo)
    assert client.put(url, json={"target_dir": "results"}, headers=admin_headers).status_code == 409  # not locked
    assert links(client, admin_headers, project) == []

    set_locked(project)
    response = client.put(url, json={"target_dir": "a", "owned_by_federated_node": False}, headers=admin_headers)
    assert response.status_code == 201 and response.json["project_id"] == project.id

    # PUT replaces: omitted fields go back to their defaults
    response = client.put(url, json={"target_dir": "b"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["target_dir"] == "b" and response.json["owned_by_federated_node"] is True
    assert len(links(client, admin_headers, project)) == 1


def test_relink_needs_drained_project(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    set_locked(project)
    make_task()  # a pending task: the project is not drained
    url = link_url(project, global_results_repo)
    assert client.put(url, json={"target_dir": "x"}, headers=admin_headers).status_code == 409
    assert client.get(url, headers=admin_headers).json["target_dir"] == "results"


def test_one_results_repo_per_project_but_repo_shared(
    client, admin_headers, project, other_project, global_results_repo, make_results_repo
):
    assert put_link(client, admin_headers, project, global_results_repo).status_code == 201
    second = make_results_repo(uri="github.com/org/second")
    assert put_link(client, admin_headers, project, second, "x").status_code == 409
    assert len(links(client, admin_headers, project)) == 1
    # another project may link the very same global repository
    assert put_link(client, admin_headers, other_project, global_results_repo, "o").status_code == 201


def test_link_target_dir_validation(client, admin_headers, lock_project, global_results_repo):
    url = link_url(lock_project, global_results_repo)
    bad_bodies = [
        {}, {"target_dir": ""}, {"target_dir": None},  # empty
        {"target_dir": "/"}, {"target_dir": "./."},  # normalises to empty
        {"target_dir": ".."}, {"target_dir": "a/../b"}, {"target_dir": "x/../../etc"},  # traversal
        {"target_dir": 123}, {"target_dir": ["a"]}, {"target_dir": True},  # non-string
        {"target_dir": "r", "bogus": 1}, {"target_dir": "r", "revoked": True},  # revoked is PATCH only
        {"target_dir": "r", "enabled": "yes"}, {"target_dir": "r", "owned_by_federated_node": 1},
    ]
    for body in bad_bodies:
        assert client.put(url, json=body, headers=admin_headers).status_code == 400, body
    assert links(client, admin_headers, lock_project) == []

    assert client.put(f"/projects/{lock_project.id}/repositories/results/999", json={"target_dir": "r"},
                      headers=admin_headers).status_code == 404
    assert client.put(f"/projects/999/repositories/results/{global_results_repo.id}", json={"target_dir": "r"},
                      headers=admin_headers).status_code == 404


def test_link_target_dir_normalised_and_never_absolute(client, admin_headers, lock_project, global_results_repo):
    url = link_url(lock_project, global_results_repo)
    response = client.put(url, json={"target_dir": "/etc/out/"}, headers=admin_headers)
    assert response.status_code == 201 and response.json["target_dir"] == "etc/out"
    response = client.put(url, json={"target_dir": "./a//b/./c/"}, headers=admin_headers)
    assert response.status_code == 200
    assert client.get(url, headers=admin_headers).json["target_dir"] == "a/b/c"


def test_patch_link_settings(client, admin_headers, project, global_results_repo, linked_results_repo):
    url = link_url(project, global_results_repo)
    set_locked(project)
    response = client.patch(url, json={"target_dir": "/new//dir/"}, headers=admin_headers)
    assert response.status_code == 200 and response.json["target_dir"] == "new/dir"
    for body in ({"target_dir": "../up"}, {"target_dir": ""}, {"bogus": 1}, {}, {"enabled": "no"}):
        assert client.patch(url, json=body, headers=admin_headers).status_code == 400, body
    assert client.get(url, headers=admin_headers).json["target_dir"] == "new/dir"


# ---------------------------------------------------------------- loop refusal (results dir vs watched dir)


def test_results_dir_inside_watched_dir_refused(
    client, admin_headers, lock_project, make_trigger_repo, make_results_repo
):
    """A results target_dir that overlaps a watched dir of the same git repository would loop."""
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    assert client.put(trigger_url(lock_project, trigger), json={"watch_dir": "/triggers/in/"},
                      headers=admin_headers).status_code == 201

    for target in ("triggers/in/out", "triggers/in", "triggers", "./triggers//in/x"):  # inside, equal, parent, unnormalised
        response = client.put(link_url(lock_project, results), json={"target_dir": target}, headers=admin_headers)
        assert response.status_code == 400, target
        assert "overlap" in response.json["error"]
    assert links(client, admin_headers, lock_project) == []

    response = client.put(link_url(lock_project, results), json={"target_dir": "triggers/out"}, headers=admin_headers)
    assert response.status_code == 201  # a sibling dir is fine

    # PATCHing the target_dir into the watched dir is refused and rolled back
    assert client.patch(link_url(lock_project, results), json={"target_dir": "triggers/in/x"},
                        headers=admin_headers).status_code == 400
    assert client.get(link_url(lock_project, results), headers=admin_headers).json["target_dir"] == "triggers/out"


def test_watch_dir_over_results_dir_refused_and_other_repo_or_project(
    client, admin_headers, project, other_project, make_trigger_repo, make_results_repo
):
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    elsewhere = make_trigger_repo(uri="github.com/org/elsewhere")
    assert put_link(client, admin_headers, project, results, "out/data").status_code == 201

    set_locked(project)
    for watch in ("out", "out/data", "out/data/sub"):
        assert client.put(trigger_url(project, trigger), json={"watch_dir": watch},
                          headers=admin_headers).status_code == 400, watch
    # a different git repository never loops, whatever the directories
    assert client.put(trigger_url(project, elsewhere), json={"watch_dir": "out/data"},
                      headers=admin_headers).status_code == 201
    # cross-project loops are forbidden too (ADR section 9)
    response = client.put(trigger_url(other_project, trigger), json={"watch_dir": "out"}, headers=admin_headers)
    assert response.status_code == 400


# ---------------------------------------------------------------- revoke / unlink


def test_revoked_link_listed_inactive_and_other_project_cannot_touch(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo
):
    url = link_url(project, global_results_repo)
    response = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert response.status_code == 200 and response.json["active"] is False and response.json["revoked"] is True
    assert [item["active"] for item in links(client, admin_headers, project)] == [False]  # listed, not dropped
    assert client.patch(url, json={"revoked": False}, headers=admin_headers).json["active"] is True

    other = link_url(other_project, global_results_repo)
    assert [client.get(other, headers=admin_headers).status_code,
            client.patch(other, json={"revoked": True}, headers=admin_headers).status_code,
            client.delete(other, headers=admin_headers).status_code] == [404, 404, 404]


def test_unlink_needs_lock_then_another_repo_can_be_linked(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_results_repo
):
    url = link_url(project, global_results_repo)
    assert client.delete(url, headers=admin_headers).status_code == 409  # not locked
    set_locked(project)
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).status_code == 404
    assert client.delete(url, headers=admin_headers).status_code == 404
    assert links(client, admin_headers, project) == []

    other = make_results_repo(uri="github.com/org/replacement")
    assert client.put(link_url(project, other), json={"target_dir": "r"}, headers=admin_headers).status_code == 201


def test_unlink_and_global_delete_refused_while_results_exist(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    """Results restrict the link, even once delivered; deleting the task cascades the result and frees the link."""
    task = make_task()
    rid = new_result(client, admin_headers, project, task, global_results_repo)
    assert patch_result(client, admin_headers, project, rid, {"step": "MERGED", "state": "DELIVERED"}).status_code == 200
    set_locked(project)
    url = link_url(project, global_results_repo)
    assert client.delete(url, headers=admin_headers).status_code in (400, 409)
    assert client.get(url, headers=admin_headers).status_code == 200

    db.session.delete(task)
    db.session.commit()
    assert client.get(f"{results_url(project)}/{rid}", headers=admin_headers).status_code == 404
    assert client.delete(url, headers=admin_headers).status_code == 204


def test_global_delete_refused_while_results_exist(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    url = f"{RESULTS_GLOBAL}/{global_results_repo.id}"
    rid = new_result(client, admin_headers, project, make_task(), global_results_repo)
    assert patch_result(client, admin_headers, project, rid, {"state": "DELIVERED"}).status_code == 200
    set_locked(project)
    assert client.delete(url, headers=admin_headers).status_code in (400, 409)
    assert client.get(url, headers=admin_headers).status_code == 200


def test_global_delete_without_results_removes_the_link(
    client, admin_headers, project, global_results_repo, linked_results_repo
):
    set_locked(project)
    assert client.delete(f"{RESULTS_GLOBAL}/{global_results_repo.id}", headers=admin_headers).status_code == 204
    assert links(client, admin_headers, project) == []


# ---------------------------------------------------------------- POST /results


def test_post_result_only_for_success_task_and_is_idempotent(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task = make_task()
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code == 409  # not SUCCESS yet
    assert client.get(results_url(project), headers=admin_headers).json == []

    rid = new_result(client, admin_headers, project, task, global_results_repo)
    body = get_result(client, admin_headers, project, rid)
    assert body["results_repository_id"] == global_results_repo.id  # the global repo id, not the link row id
    assert (body["task_id"], body["project_id"], body["type"]) == (task.id, project.id, "PR")
    assert (body["step"], body["state"], body["attempts"], body["error"]) == ("UNKNOWN", "IN_PROGRESS", 0, None)

    assert patch_result(client, admin_headers, project, rid, {"step": "PUSHED"}).status_code == 200
    again = post_result(client, admin_headers, project, task, global_results_repo)
    assert again.status_code == 200 and again.json["id"] == rid and again.json["step"] == "PUSHED"  # progress kept


def test_post_result_refusals(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo, make_task, make_results_repo
):
    ok_task = make_task(status="SUCCESS")
    good = {"task_id": ok_task.id, "results_repository_id": global_results_repo.id}
    unlinked = make_results_repo(uri="github.com/org/unlinked")

    # task of another project: 404
    assert post_result(client, admin_headers, project, make_task(project=other_project), global_results_repo).status_code == 404
    assert client.post(results_url(project), json={**good, "task_id": 999}, headers=admin_headers).status_code == 404
    assert client.post("/projects/999/results", json=good, headers=admin_headers).status_code == 404
    # repository not linked to the project: 400
    assert post_result(client, admin_headers, project, ok_task, unlinked).status_code == 400
    assert client.post(results_url(project), json={**good, "results_repository_id": 999}, headers=admin_headers).status_code == 400
    # malformed bodies: 400
    for body in ({}, {"task_id": ok_task.id}, {**good, "task_id": True}, {**good, "task_id": "x"},
                 {**good, "results_repository_id": "1"}):
        assert client.post(results_url(project), json=body, headers=admin_headers).status_code == 400, body
    assert client.post(results_url(project), json=[1], headers=admin_headers).status_code == 400
    # revoked link: the result is created as final, REVOKED and FAILED, and nothing is ever delivered for it
    assert client.patch(link_url(project, global_results_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    created = post_result(client, admin_headers, project, ok_task, global_results_repo)
    assert created.status_code == 201 and created.json["step"] == "REVOKED" and created.json["state"] == "FAILED"
    assert post_result(client, admin_headers, project, ok_task, global_results_repo).status_code == 200  # same result
    assert patch_result(client, admin_headers, project, created.json["id"], {"step": "PUSHED"}).status_code == 400
    # un-revoking the link does not deliver it
    assert client.patch(link_url(project, global_results_repo), json={"revoked": False}, headers=admin_headers).status_code == 200
    assert get_result(client, admin_headers, project, created.json["id"])["step"] == "REVOKED"


# ---------------------------------------------------------------- PATCH /results/<id>


def test_step_is_forward_only(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    def fresh():
        return new_result(client, admin_headers, project, make_task(), global_results_repo)

    rid = fresh()
    for step in ("PUSHED", "OPENED", "OPENED", "MERGED"):  # forward, same step again is allowed
        assert patch_result(client, admin_headers, project, rid, {"step": step}).json["step"] == step
    for backwards in ("OPENED", "UNKNOWN", "CLOSED", "REVOKED"):  # MERGED, CLOSED and REVOKED are terminal siblings
        assert patch_result(client, admin_headers, project, rid, {"step": backwards}).status_code == 400
    assert get_result(client, admin_headers, project, rid)["step"] == "MERGED"

    rid = fresh()  # steps may be skipped
    assert patch_result(client, admin_headers, project, rid, {"step": "CLOSED"}).status_code == 200
    assert patch_result(client, admin_headers, project, rid, {"step": "PUSHED"}).status_code == 400


def test_state_changes_freely_but_only_to_valid_values(client, admin_headers, project, result_id):
    for state in ("DELIVERED", "FAILED", "IN_PROGRESS", "DELIVERED"):  # a failed delivery can be re-launched
        assert patch_result(client, admin_headers, project, result_id, {"state": state}).json["state"] == state
    for bad in ("delivered", "DONE", "", None, 1):
        assert patch_result(client, admin_headers, project, result_id, {"state": bad}).status_code == 400, bad
    for bad in ("BOGUS", "opened", None, 2, ["OPENED"]):
        assert patch_result(client, admin_headers, project, result_id, {"step": bad}).status_code == 400, bad
    assert get_result(client, admin_headers, project, result_id)["state"] == "DELIVERED"


def test_patch_all_fields_and_reset_to_null(client, admin_headers, project, result_id):
    response = patch_result(client, admin_headers, project, result_id, {
        "step": "OPENED", "state": "DELIVERED", "attempts": 2, "branch": "fn/1", "commit_sha": "a" * 40,
        "number": 9, "url": "https://x/pull/9", "merge_commit_sha": "b" * 40, "merged_at": "2030-01-02T03:04:05Z",
    })
    assert response.status_code == 200, response.json
    assert (response.json["step"], response.json["attempts"], response.json["number"]) == ("OPENED", 2, 9)
    assert response.json["merged_at"].startswith("2030-01-02T03:04:05")

    response = patch_result(client, admin_headers, project, result_id,
                            {"state": "FAILED", "error": "boom", "url": None, "merged_at": None})
    assert response.status_code == 200
    assert (response.json["error"], response.json["url"], response.json["merged_at"]) == ("boom", None, None)
    assert response.json["step"] == "OPENED"


def test_patch_invalid_fields_refused_and_nothing_applied(client, admin_headers, project, result_id):
    bad_bodies = [
        {"number": "5"}, {"number": 5.5}, {"number": True}, {"number": -1},  # integers only, not negative
        {"attempts": "1"}, {"attempts": -1},
        {"url": 5}, {"url": "u" * 4097}, {"commit_sha": "a" * 41}, {"merge_commit_sha": "a" * 41},
        {"branch": "b" * 257}, {"branch": 7}, {"error": "e" * 1025},
        {"merged_at": "not a date"}, {"merged_at": 123},
        {"bogus": 1}, {"id": 1}, {"task_id": 1}, {"results_repository_id": 1}, {"project_id": 1}, {"type": "PR"},  # unknown/immutable
        {},
        {"step": "PUSHED", "state": "NOPE"}, {"step": "OPENED", "bogus": 1},  # a bad field voids the valid one
    ]
    for body in bad_bodies:
        assert patch_result(client, admin_headers, project, result_id, body).status_code == 400, body
    got = get_result(client, admin_headers, project, result_id)
    assert (got["step"], got["state"], got["number"], got["attempts"]) == ("UNKNOWN", "IN_PROGRESS", None, 0)
    assert patch_result(client, admin_headers, project, 99999, {"step": "PUSHED"}).status_code == 404


# ---------------------------------------------------------------- GET filters and project scoping


def test_list_filter_by_step(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    ids = {}
    for step in ("UNKNOWN", "PUSHED", "OPENED", "MERGED"):
        ids[step] = new_result(client, admin_headers, project, make_task(), global_results_repo)
        if step != "UNKNOWN":
            assert patch_result(client, admin_headers, project, ids[step], {"step": step}).status_code == 200
    url = results_url(project)

    def listed(query):
        response = client.get(f"{url}{query}", headers=admin_headers)
        assert response.status_code == 200
        return [r["id"] for r in response.json]

    assert listed("") == sorted(ids.values())
    assert listed("?step=PUSHED") == [ids["PUSHED"]]
    assert listed("?step=PUSHED&step=OPENED") == [ids["PUSHED"], ids["OPENED"]]
    assert listed("?step=PUSHED&bogus=x&page=2") == [ids["PUSHED"]]  # unknown params are ignored
    for query in ("?step=NOPE", "?step=opened", "?step=PUSHED&step=NOPE"):
        assert client.get(f"{url}{query}", headers=admin_headers).status_code == 400, query


def test_results_are_scoped_to_their_project(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo, make_task
):
    mine = new_result(client, admin_headers, project, make_task(), global_results_repo)
    assert put_link(client, admin_headers, other_project, global_results_repo, "o").status_code == 201
    theirs = new_result(client, admin_headers, other_project, make_task(project=other_project), global_results_repo)
    assert patch_result(client, admin_headers, other_project, theirs, {"step": "OPENED"}).status_code == 200

    assert [r["id"] for r in client.get(results_url(project), headers=admin_headers).json] == [mine]
    assert client.get(f"{results_url(project)}?step=OPENED", headers=admin_headers).json == []
    assert [r["id"] for r in client.get(f"{results_url(other_project)}?step=OPENED", headers=admin_headers).json] == [theirs]
    # a result is invisible and immutable from the other project; unknown ids and projects are 404
    assert client.get(f"{results_url(other_project)}/{mine}", headers=admin_headers).status_code == 404
    assert patch_result(client, admin_headers, other_project, mine, {"step": "MERGED"}).status_code == 404
    assert get_result(client, admin_headers, project, mine)["step"] == "UNKNOWN"
    assert client.get(f"{results_url(project)}/99999", headers=admin_headers).status_code == 404
    assert client.get("/projects/99999/results", headers=admin_headers).status_code == 404


def test_task_results_route(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    task = make_task()
    rid = new_result(client, admin_headers, project, task, global_results_repo)
    response = client.get(f"/projects/{project.id}/tasks/{task.id}/results", headers=admin_headers)
    assert [r["id"] for r in response.json] == [rid]
    assert response.json[0]["results_repository_id"] == global_results_repo.id
