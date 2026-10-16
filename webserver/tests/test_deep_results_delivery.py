"""
Deep tests for results repositories and PR results (ADR 0019 sections 8 and 11):
target_dir validation, one results repository per project, relink/unlink, result creation rules,
step ordering, field validation, filters and cascades.
"""
import pytest

from app.helpers.base_model import db
from app.models.task_status import TaskStatus


def link_url(project, repo):
    return f"/projects/{project.id}/repositories/results/{repo.id}"


def trigger_url(project, repo):
    return f"/projects/{project.id}/repositories/triggers/{repo.id}"


def results_url(project):
    return f"/projects/{getattr(project, 'id', project)}/results"


def set_locked(project, locked=True):
    project.locked = locked
    db.session.commit()


def put_link(client, admin_headers, project, repo, target_dir="results", **extra):
    """Link the results repository (the PUT needs the project locked); returns the response, project unlocked."""
    set_locked(project, True)
    response = client.put(link_url(project, repo), json={"target_dir": target_dir, **extra}, headers=admin_headers)
    set_locked(project, False)
    return response


def post_result(client, admin_headers, project, task, repo):
    return client.post(
        results_url(project),
        json={"task_id": task.id, "results_repository_id": repo.id},
        headers=admin_headers,
    )


def new_result(client, admin_headers, project, task, repo):
    response = post_result(client, admin_headers, project, task, repo)
    assert response.status_code == 201, response.json
    return response.json["id"]


def patch_result(client, admin_headers, project, rid, body):
    return client.patch(f"{results_url(project)}/{rid}", json=body, headers=admin_headers)


@pytest.fixture
def result_id(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    """A result (step UNKNOWN) of a fresh task, on the linked repository."""
    return new_result(client, admin_headers, project, make_task(), global_results_repo)


# ---------------------------------------------------------------- target_dir validation


def test_link_empty_target_dir_refused(client, admin_headers, lock_project, global_results_repo):
    for body in ({"target_dir": ""}, {"target_dir": None}, {}):
        response = client.put(link_url(lock_project, global_results_repo), json=body, headers=admin_headers)
        assert response.status_code == 400, body
    response = client.get(f"/projects/{lock_project.id}/repositories/results", headers=admin_headers)
    assert response.json == []


@pytest.mark.parametrize("target_dir", ["/", "//", ".", "./", "./."])
def test_link_target_dir_that_normalises_to_empty_refused(
    client, admin_headers, lock_project, global_results_repo, target_dir
):
    response = client.put(
        link_url(lock_project, global_results_repo), json={"target_dir": target_dir}, headers=admin_headers
    )
    assert response.status_code == 400


@pytest.mark.parametrize("target_dir", ["..", "../x", "a/../b", "a/b/..", "x/../../etc"])
def test_link_target_dir_traversal_refused(client, admin_headers, lock_project, global_results_repo, target_dir):
    response = client.put(
        link_url(lock_project, global_results_repo), json={"target_dir": target_dir}, headers=admin_headers
    )
    assert response.status_code == 400
    # nothing was linked
    response = client.get(f"/projects/{lock_project.id}/repositories/results", headers=admin_headers)
    assert response.json == []


def test_link_absolute_target_dir_is_never_absolute_in_the_link(
    client, admin_headers, lock_project, global_results_repo
):
    """ADR is silent: either refuse an absolute path or store it relative. It must not stay absolute."""
    response = client.put(
        link_url(lock_project, global_results_repo), json={"target_dir": "/etc/out"}, headers=admin_headers
    )
    assert response.status_code in (201, 400)
    if response.status_code == 201:
        assert not response.json["target_dir"].startswith("/")
        assert response.json["target_dir"] == "etc/out"


def test_link_target_dir_slashes_are_normalised(client, admin_headers, lock_project, global_results_repo):
    url = link_url(lock_project, global_results_repo)
    response = client.put(url, json={"target_dir": "/out/"}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json["target_dir"] == "out"

    response = client.put(url, json={"target_dir": "./a//b/./c/"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["target_dir"] == "a/b/c"
    assert client.get(url, headers=admin_headers).json["target_dir"] == "a/b/c"


def test_link_nested_target_dir_ok(client, admin_headers, lock_project, global_results_repo):
    response = client.put(
        link_url(lock_project, global_results_repo),
        json={"target_dir": "deep/er/results"}, headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json["target_dir"] == "deep/er/results"
    assert response.json["project_id"] == lock_project.id


@pytest.mark.xfail(reason="non-string target_dir is not validated (expected 400)", strict=False)
@pytest.mark.parametrize("target_dir", [123, ["a"], {"a": 1}, True])
def test_link_non_string_target_dir_refused(client, admin_headers, lock_project, global_results_repo, target_dir):
    response = client.put(
        link_url(lock_project, global_results_repo), json={"target_dir": target_dir}, headers=admin_headers
    )
    assert response.status_code == 400


def test_link_bad_body_fields(client, admin_headers, lock_project, global_results_repo):
    url = link_url(lock_project, global_results_repo)
    for body in (
        {"target_dir": "r", "bogus": 1},
        {"target_dir": "r", "revoked": True},  # revoked is PATCH only
        {"target_dir": "r", "enabled": "yes"},
        {"target_dir": "r", "owned_by_federated_node": 1},
    ):
        assert client.put(url, json=body, headers=admin_headers).status_code == 400, body


def test_link_unknown_repo_and_project(client, admin_headers, lock_project, global_results_repo):
    response = client.put(
        f"/projects/{lock_project.id}/repositories/results/999", json={"target_dir": "r"}, headers=admin_headers
    )
    assert response.status_code == 404
    response = client.put(
        f"/projects/999/repositories/results/{global_results_repo.id}", json={"target_dir": "r"}, headers=admin_headers
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- overlap with a watched trigger dir


def test_results_into_watched_dir_overlap_refused_trigger_first(
    client, admin_headers, lock_project, make_trigger_repo, make_results_repo
):
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    response = client.put(trigger_url(lock_project, trigger), json={"watch_dir": "triggers/in"}, headers=admin_headers)
    assert response.status_code == 201

    # inside, equal, and a parent of the watched dir all overlap
    for target in ("triggers/in/out", "triggers/in", "triggers"):
        response = client.put(link_url(lock_project, results), json={"target_dir": target}, headers=admin_headers)
        assert response.status_code == 400, target
        assert "overlap" in response.json["error"]
    assert client.get(f"/projects/{lock_project.id}/repositories/results", headers=admin_headers).json == []

    # a sibling dir is fine
    response = client.put(link_url(lock_project, results), json={"target_dir": "triggers/out"}, headers=admin_headers)
    assert response.status_code == 201


def test_trigger_watch_dir_overlapping_results_dir_refused_results_first(
    client, admin_headers, lock_project, make_trigger_repo, make_results_repo
):
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    response = client.put(link_url(lock_project, results), json={"target_dir": "out/data"}, headers=admin_headers)
    assert response.status_code == 201

    for watch in ("out", "out/data", "out/data/sub"):
        response = client.put(trigger_url(lock_project, trigger), json={"watch_dir": watch}, headers=admin_headers)
        assert response.status_code == 400, watch
    response = client.get(f"/projects/{lock_project.id}/repositories/triggers", headers=admin_headers)
    assert response.json == []

    response = client.put(trigger_url(lock_project, trigger), json={"watch_dir": "triggers"}, headers=admin_headers)
    assert response.status_code == 201


def test_overlap_check_normalises_slashes(client, admin_headers, lock_project, make_trigger_repo, make_results_repo):
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    assert client.put(
        trigger_url(lock_project, trigger), json={"watch_dir": "/triggers/"}, headers=admin_headers
    ).status_code == 201
    response = client.put(link_url(lock_project, results), json={"target_dir": "./triggers//x"}, headers=admin_headers)
    assert response.status_code == 400


def test_overlap_only_within_same_repository(client, admin_headers, lock_project, global_trigger_repo, make_results_repo):
    """Different repositories (uris) never loop, whatever the directories."""
    assert client.put(
        trigger_url(lock_project, global_trigger_repo), json={"watch_dir": "same"}, headers=admin_headers
    ).status_code == 201
    other = make_results_repo(uri="github.com/org/elsewhere")
    response = client.put(link_url(lock_project, other), json={"target_dir": "same"}, headers=admin_headers)
    assert response.status_code == 201


def test_cross_project_loop_refused(
    client, admin_headers, project, other_project, make_trigger_repo, make_results_repo
):
    """ADR section 9: cross-project loops are forbidden too."""
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    assert client.put(trigger_url(other_project, trigger), json={"watch_dir": "in"}, headers=admin_headers).status_code == 201
    response = put_link(client, admin_headers, project, results, "in/out")
    assert response.status_code == 400
    assert "overlap" in response.json["error"]


def test_patch_target_dir_into_watched_dir_refused_and_rolled_back(
    client, admin_headers, project, make_trigger_repo, make_results_repo
):
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    assert client.put(trigger_url(project, trigger), json={"watch_dir": "in"}, headers=admin_headers).status_code == 201
    assert put_link(client, admin_headers, project, results, "out").status_code == 201

    set_locked(project)
    response = client.patch(link_url(project, results), json={"target_dir": "in/x"}, headers=admin_headers)
    assert response.status_code == 400
    assert client.get(link_url(project, results), headers=admin_headers).json["target_dir"] == "out"


# ---------------------------------------------------------------- one repo per project, relink, unlink


def test_one_results_repo_per_project_but_repo_shared_between_projects(
    client, admin_headers, project, other_project, global_results_repo, make_results_repo
):
    assert put_link(client, admin_headers, project, global_results_repo).status_code == 201
    second = make_results_repo(uri="github.com/org/second")
    response = put_link(client, admin_headers, project, second, "x")
    assert response.status_code == 409
    # still only the first link
    listing = client.get(f"/projects/{project.id}/repositories/results", headers=admin_headers).json
    assert [item["results_repository"]["id"] if "results_repository" in item else None for item in listing] != []
    assert len(listing) == 1

    # another project may link the very same global repository
    assert put_link(client, admin_headers, other_project, global_results_repo, "o").status_code == 201


def test_relink_same_repo_replaces_settings(client, admin_headers, project, global_results_repo):
    assert put_link(client, admin_headers, project, global_results_repo, "a", owned_by_federated_node=False).status_code == 201
    set_locked(project)
    url = link_url(project, global_results_repo)

    # PUT replaces: fields left out take their defaults
    response = client.put(url, json={"target_dir": "b"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["target_dir"] == "b"
    assert response.json["owned_by_federated_node"] is True
    assert response.json["enabled"] is True


def test_relink_needs_drained_project(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    url = link_url(project, global_results_repo)
    # unlocked
    assert client.put(url, json={"target_dir": "x"}, headers=admin_headers).status_code == 409
    # locked, but a pending task
    set_locked(project)
    make_task()
    response = client.put(url, json={"target_dir": "x"}, headers=admin_headers)
    assert response.status_code == 409
    assert client.get(url, headers=admin_headers).json["target_dir"] == "results"


def test_unlink_then_link_another_repo(client, admin_headers, project, global_results_repo, linked_results_repo, make_results_repo):
    url = link_url(project, global_results_repo)
    set_locked(project)
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).status_code == 404
    assert client.get(f"/projects/{project.id}/repositories/results", headers=admin_headers).json == []
    assert client.delete(url, headers=admin_headers).status_code == 404

    other = make_results_repo(uri="github.com/org/replacement")
    response = client.put(link_url(project, other), json={"target_dir": "r"}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json["results_repository"]["id"] == other.id if "results_repository" in response.json else True


def test_unlink_needs_lock(client, admin_headers, project, global_results_repo, linked_results_repo):
    assert client.delete(link_url(project, global_results_repo), headers=admin_headers).status_code == 409
    assert client.get(link_url(project, global_results_repo), headers=admin_headers).status_code == 200


def test_patch_link_settings(client, admin_headers, project, global_results_repo, linked_results_repo):
    url = link_url(project, global_results_repo)
    set_locked(project)

    response = client.patch(url, json={"target_dir": "/new//dir/"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["target_dir"] == "new/dir"

    for body in ({"target_dir": "../up"}, {"target_dir": ""}, {"target_dir": "/"}, {"bogus": 1}, {}, {"enabled": "no"}):
        assert client.patch(url, json=body, headers=admin_headers).status_code == 400, body
    assert client.get(url, headers=admin_headers).json["target_dir"] == "new/dir"


def test_revoked_link_is_still_listed_inactive(client, admin_headers, project, global_results_repo, linked_results_repo):
    """ADR section 5: an inactive link is returned with its flags, not dropped."""
    url = link_url(project, global_results_repo)
    response = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["active"] is False
    assert response.json["revoked"] is True

    listing = client.get(f"/projects/{project.id}/repositories/results", headers=admin_headers).json
    assert len(listing) == 1
    assert listing[0]["active"] is False

    response = client.patch(url, json={"revoked": False}, headers=admin_headers)
    assert response.json["active"] is True


def test_other_project_cannot_see_or_touch_link(
    client, admin_headers, other_project, global_results_repo, linked_results_repo
):
    url = link_url(other_project, global_results_repo)
    assert client.get(url, headers=admin_headers).status_code == 404
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 404
    assert client.delete(url, headers=admin_headers).status_code == 404
    assert client.get(f"/projects/{other_project.id}/repositories/results", headers=admin_headers).json == []


# ---------------------------------------------------------------- result creation rules


@pytest.mark.parametrize("status", ["SUCCESS", "PENDING", "RUNNING"])
def test_post_result_for_task_states_current_behaviour(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task, status
):
    """The ADR does not restrict the task status on POST (the plan posts for a PENDING task): any is accepted."""
    task = make_task(status=status)
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code == 201


@pytest.mark.xfail(reason="results are accepted for FAILED/CANCELED tasks, which produce nothing to deliver", strict=False)
@pytest.mark.parametrize("status", ["FAILED", "CANCELED"])
def test_post_result_for_dead_task_refused(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task, status
):
    task = make_task(status=status)
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code in (400, 409)


def test_post_result_shape_and_global_repo_id(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo, make_task
):
    """The result carries the global repository id, not the id of the project's link row."""
    # Give another project a link first, so the two link ids differ from the repository id
    assert put_link(client, admin_headers, other_project, global_results_repo, "o").status_code == 201
    second = Link = None  # noqa: F841  (placeholder to keep the arrangement explicit)
    task = make_task(status="SUCCESS")
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 201
    body = response.json
    assert body["results_repository_id"] == global_results_repo.id
    assert body["task_id"] == task.id
    assert body["project_id"] == project.id
    assert body["type"] == "PR"
    assert body["step"] == "UNKNOWN" and body["state"] == "IN_PROGRESS"
    assert body["attempts"] == 0 and body["error"] is None
    assert body["number"] is None and body["url"] is None and body["branch"] is None
    assert body["created_at"] and body["updated_at"]


def test_post_result_duplicate_is_idempotent_per_task_and_repo(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    first, second = make_task(), make_task()
    rid = new_result(client, admin_headers, project, first, global_results_repo)
    # progress must survive a repeated POST
    assert patch_result(client, admin_headers, project, rid, {"step": "PUSHED"}).status_code == 200

    again = post_result(client, admin_headers, project, first, global_results_repo)
    assert again.status_code == 200
    assert again.json["id"] == rid and again.json["step"] == "PUSHED"

    other = post_result(client, admin_headers, project, second, global_results_repo)
    assert other.status_code == 201 and other.json["id"] != rid


def test_post_result_task_of_another_project_is_404(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo, make_task
):
    foreign = make_task(project=other_project)
    response = post_result(client, admin_headers, project, foreign, global_results_repo)
    assert response.status_code == 404
    # nothing listed anywhere
    assert client.get(results_url(project), headers=admin_headers).json == []
    assert client.get(results_url(other_project), headers=admin_headers).json == []


def test_post_result_repo_not_linked_is_400(client, admin_headers, project, global_results_repo, make_task):
    task = make_task()
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 400
    assert client.get(results_url(project), headers=admin_headers).json == []


def test_post_result_repo_linked_to_other_project_only_is_400(
    client, admin_headers, project, other_project, global_results_repo, make_task
):
    assert put_link(client, admin_headers, other_project, global_results_repo).status_code == 201
    task = make_task()
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code == 400


@pytest.mark.xfail(reason="POST /results accepts a revoked link (ADR 2/12.1: revoke takes effect immediately)", strict=False)
def test_post_result_revoked_link_refused(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    assert client.patch(link_url(project, global_results_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    task = make_task(status="SUCCESS")
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code in (400, 403, 409)


@pytest.mark.xfail(reason="POST /results accepts a link the project disabled (inactive link)", strict=False)
def test_post_result_disabled_link_refused(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    set_locked(project)
    assert client.patch(link_url(project, global_results_repo), json={"enabled": False}, headers=admin_headers).status_code == 200
    set_locked(project, False)
    task = make_task(status="SUCCESS")
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code in (400, 409)


@pytest.mark.xfail(reason="POST /results accepts a globally disabled results repository", strict=False)
def test_post_result_globally_disabled_repo_refused(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    global_results_repo.enabled = False
    db.session.commit()
    task = make_task(status="SUCCESS")
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code in (400, 409)


def test_post_result_bad_bodies(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    task = make_task()
    good = {"task_id": task.id, "results_repository_id": global_results_repo.id}
    bad = [
        {},
        {"task_id": task.id},
        {"results_repository_id": global_results_repo.id},
        {**good, "task_id": True},
        {**good, "task_id": None},
        {**good, "task_id": 1.5},
        {**good, "results_repository_id": "1"},
        {**good, "results_repository_id": [1]},
    ]
    for body in bad:
        response = client.post(results_url(project), json=body, headers=admin_headers)
        assert response.status_code == 400, body
    assert client.post(results_url(999), json=good, headers=admin_headers).status_code == 404
    assert client.get(results_url(project), headers=admin_headers).json == []


def test_post_result_non_object_body(client, admin_headers, project, linked_results_repo):
    assert client.post(results_url(project), json=[1], headers=admin_headers).status_code == 400


def test_results_repo_delete_with_result_in_other_project_does_not_mix(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo, make_task
):
    """Two projects share one global repo: each tracks its own result against its own link."""
    assert put_link(client, admin_headers, other_project, global_results_repo, "o").status_code == 201
    mine = new_result(client, admin_headers, project, make_task(), global_results_repo)
    theirs = new_result(client, admin_headers, other_project, make_task(project=other_project), global_results_repo)
    assert client.get(results_url(project), headers=admin_headers).json[0]["id"] == mine
    assert [r["id"] for r in client.get(results_url(other_project), headers=admin_headers).json] == [theirs]


# ---------------------------------------------------------------- step ordering


def test_step_walks_forward_and_may_skip(client, admin_headers, project, result_id):
    for step in ("PUSHED", "OPENED", "MERGED"):
        response = patch_result(client, admin_headers, project, result_id, {"step": step})
        assert response.status_code == 200, step
        assert response.json["step"] == step


def test_step_skipping_straight_to_merged_is_allowed(client, admin_headers, project, result_id):
    response = patch_result(client, admin_headers, project, result_id, {"step": "MERGED"})
    assert response.status_code == 200
    assert response.json["step"] == "MERGED"


@pytest.mark.parametrize("path", [
    ["OPENED", "PUSHED"],
    ["OPENED", "UNKNOWN"],
    ["PUSHED", "UNKNOWN"],
    ["MERGED", "OPENED"],
    ["CLOSED", "PUSHED"],
])
def test_step_backwards_refused_and_unchanged(client, admin_headers, project, result_id, path):
    start, backwards = path
    assert patch_result(client, admin_headers, project, result_id, {"step": start}).status_code == 200
    assert patch_result(client, admin_headers, project, result_id, {"step": backwards}).status_code == 400
    got = client.get(f"{results_url(project)}/{result_id}", headers=admin_headers)
    assert got.json["step"] == start


def test_step_same_step_again_is_allowed(client, admin_headers, project, result_id):
    for _ in range(2):
        assert patch_result(client, admin_headers, project, result_id, {"step": "OPENED"}).status_code == 200
    assert patch_result(client, admin_headers, project, result_id, {"step": "UNKNOWN"}).status_code == 400


@pytest.mark.parametrize("first,second", [("MERGED", "CLOSED"), ("CLOSED", "MERGED")])
def test_terminal_steps_do_not_switch(client, admin_headers, project, result_id, first, second):
    assert patch_result(client, admin_headers, project, result_id, {"step": first}).status_code == 200
    assert patch_result(client, admin_headers, project, result_id, {"step": second}).status_code == 400
    assert patch_result(client, admin_headers, project, result_id, {"step": first}).status_code == 200


@pytest.mark.parametrize("step", ["BOGUS", "opened", "", None, 2])
def test_invalid_step_values_refused(client, admin_headers, project, result_id, step):
    assert patch_result(client, admin_headers, project, result_id, {"step": step}).status_code == 400


@pytest.mark.xfail(reason="unhashable step (list/object) gives a 500 instead of 400", strict=False)
@pytest.mark.parametrize("step", [["OPENED"], {"a": 1}])
def test_unhashable_step_refused(client, admin_headers, project, result_id, step):
    assert patch_result(client, admin_headers, project, result_id, {"step": step}).status_code == 400


# ---------------------------------------------------------------- state


def test_state_values_and_transitions(client, admin_headers, project, result_id):
    assert client.get(f"{results_url(project)}/{result_id}", headers=admin_headers).json["state"] == "IN_PROGRESS"
    # a failed delivery can be re-launched, so the states are not one-way
    for state in ("DELIVERED", "FAILED", "IN_PROGRESS", "DELIVERED"):
        response = patch_result(client, admin_headers, project, result_id, {"state": state})
        assert response.status_code == 200, state
        assert response.json["state"] == state


@pytest.mark.parametrize("state", ["delivered", "DONE", "", None, 1, True])
def test_invalid_state_refused(client, admin_headers, project, result_id, state):
    assert patch_result(client, admin_headers, project, result_id, {"state": state}).status_code == 400
    assert client.get(f"{results_url(project)}/{result_id}", headers=admin_headers).json["state"] == "IN_PROGRESS"


def test_step_and_state_together_and_error_with_attempts(client, admin_headers, project, result_id):
    response = patch_result(client, admin_headers, project, result_id, {
        "step": "OPENED", "state": "DELIVERED", "attempts": 2, "error": None, "branch": "fn/1",
        "commit_sha": "a" * 40, "number": 9, "url": "https://x/pull/9", "merge_commit_sha": "b" * 40,
        "merged_at": "2030-01-02T03:04:05Z",
    })
    assert response.status_code == 200, response.json
    body = response.json
    assert (body["step"], body["state"], body["attempts"], body["branch"], body["number"]) == (
        "OPENED", "DELIVERED", 2, "fn/1", 9
    )
    assert body["merged_at"].startswith("2030-01-02T03:04:05")

    response = patch_result(client, admin_headers, project, result_id, {"state": "FAILED", "error": "boom"})
    assert response.json["error"] == "boom" and response.json["step"] == "OPENED"


@pytest.mark.xfail(reason="PATCH {step valid, state invalid} returns 400 but the step change is persisted", strict=False)
def test_failed_patch_applies_nothing(client, admin_headers, project, result_id):
    """A request with a bad field must not leave the valid ones half-applied."""
    response = patch_result(client, admin_headers, project, result_id, {"step": "PUSHED", "state": "NOPE"})
    assert response.status_code == 400
    got = client.get(f"{results_url(project)}/{result_id}", headers=admin_headers).json
    assert got["step"] == "UNKNOWN" and got["state"] == "IN_PROGRESS"


# ---------------------------------------------------------------- number / url / other field validation


@pytest.mark.parametrize("number", ["5", 5.5, True, [5], None])
def test_number_must_be_integer(client, admin_headers, project, result_id, number):
    assert patch_result(client, admin_headers, project, result_id, {"number": number}).status_code == 400


def test_number_integer_ok_and_persisted(client, admin_headers, project, result_id):
    response = patch_result(client, admin_headers, project, result_id, {"number": 12})
    assert response.status_code == 200 and response.json["number"] == 12
    assert client.get(f"{results_url(project)}/{result_id}", headers=admin_headers).json["number"] == 12


@pytest.mark.parametrize("attempts", ["1", 1.2, False])
def test_attempts_must_be_integer(client, admin_headers, project, result_id, attempts):
    assert patch_result(client, admin_headers, project, result_id, {"attempts": attempts}).status_code == 400


@pytest.mark.xfail(reason="negative number/attempts are accepted (expected 400)", strict=False)
@pytest.mark.parametrize("field", ["number", "attempts"])
def test_negative_counters_refused(client, admin_headers, project, result_id, field):
    assert patch_result(client, admin_headers, project, result_id, {field: -1}).status_code == 400


@pytest.mark.parametrize("field,value", [
    ("url", 5), ("url", ["x"]), ("url", "u" * 4097),
    ("commit_sha", "a" * 41), ("merge_commit_sha", "a" * 41), ("branch", "b" * 257),
    ("error", "e" * 1025), ("branch", 7),
])
def test_string_fields_validated(client, admin_headers, project, result_id, field, value):
    assert patch_result(client, admin_headers, project, result_id, {field: value}).status_code == 400


@pytest.mark.xfail(reason="a url of 4096 chars (valid) gives a 500: the audit row details column overflows", strict=False)
def test_url_at_limit_ok(client, admin_headers, project, result_id):
    assert patch_result(client, admin_headers, project, result_id, {"url": "u" * 4096}).status_code == 200


def test_string_fields_at_limit_and_null_ok(client, admin_headers, project, result_id):
    body = {"url": "u" * 200, "commit_sha": "a" * 40, "branch": "b" * 256, "error": "e" * 1024}
    assert patch_result(client, admin_headers, project, result_id, body).status_code == 200
    response = patch_result(client, admin_headers, project, result_id, {"url": None, "error": None})
    assert response.status_code == 200 and response.json["url"] is None


@pytest.mark.parametrize("merged_at", ["not a date", 123, ["2030-01-01"], True])
def test_merged_at_validated(client, admin_headers, project, result_id, merged_at):
    assert patch_result(client, admin_headers, project, result_id, {"merged_at": merged_at}).status_code == 400


def test_merged_at_accepts_iso_and_null(client, admin_headers, project, result_id):
    response = patch_result(client, admin_headers, project, result_id, {"merged_at": "2030-05-06T07:08:09"})
    assert response.status_code == 200 and response.json["merged_at"].startswith("2030-05-06T07:08:09")
    response = patch_result(client, admin_headers, project, result_id, {"merged_at": None})
    assert response.status_code == 200 and response.json["merged_at"] is None


# ---------------------------------------------------------------- PATCH of unknown / immutable fields


@pytest.mark.parametrize("field", ["bogus", "id", "task_id", "results_repository_id", "type", "project_id",
                                   "created_at", "updated_at"])
def test_patch_immutable_or_unknown_fields_refused(client, admin_headers, project, result_id, field):
    assert patch_result(client, admin_headers, project, result_id, {field: 1}).status_code == 400


def test_patch_valid_plus_unknown_applies_nothing(client, admin_headers, project, result_id):
    response = patch_result(client, admin_headers, project, result_id, {"step": "OPENED", "bogus": 1})
    assert response.status_code == 400
    assert client.get(f"{results_url(project)}/{result_id}", headers=admin_headers).json["step"] == "UNKNOWN"


def test_patch_empty_body_refused(client, admin_headers, project, result_id):
    assert patch_result(client, admin_headers, project, result_id, {}).status_code == 400


def test_patch_unknown_result_404(client, admin_headers, project, result_id):
    assert patch_result(client, admin_headers, project, 99999, {"step": "PUSHED"}).status_code == 404


# ---------------------------------------------------------------- GET filters, cross-project


def make_results_at_steps(client, admin_headers, project, repo, make_task, steps):
    ids = {}
    for step in steps:
        rid = new_result(client, admin_headers, project, make_task(), repo)
        if step != "UNKNOWN":
            assert patch_result(client, admin_headers, project, rid, {"step": step}).status_code == 200
        ids[step] = rid
    return ids


def test_list_filter_by_single_and_repeated_step(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    ids = make_results_at_steps(
        client, admin_headers, project, global_results_repo, make_task,
        ["UNKNOWN", "PUSHED", "OPENED", "MERGED", "CLOSED"],
    )
    url = results_url(project)

    def listed(query):
        response = client.get(f"{url}{query}", headers=admin_headers)
        assert response.status_code == 200
        return [r["id"] for r in response.json]

    assert listed("") == sorted(ids.values())
    assert listed("?step=PUSHED") == [ids["PUSHED"]]
    assert listed("?step=UNKNOWN") == [ids["UNKNOWN"]]
    assert listed("?step=PUSHED&step=OPENED") == [ids["PUSHED"], ids["OPENED"]]
    assert listed("?step=MERGED&step=CLOSED") == [ids["MERGED"], ids["CLOSED"]]


@pytest.mark.parametrize("query", ["?step=NOPE", "?step=opened", "?step=", "?step=PUSHED&step=NOPE"])
def test_list_invalid_step_filter_400(client, admin_headers, project, linked_results_repo, query):
    assert client.get(f"{results_url(project)}{query}", headers=admin_headers).status_code == 400


def test_list_unknown_query_params_ignored(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task, result_id
):
    """Results are a plain list (no pagination envelope); unknown params must not break or filter it."""
    for _ in range(3):
        new_result(client, admin_headers, project, make_task(), global_results_repo)
    response = client.get(f"{results_url(project)}?page=2&limit=1&bogus=x", headers=admin_headers)
    assert response.status_code == 200
    assert isinstance(response.json, list)
    assert len(response.json) == 4


def test_list_excludes_other_projects_results(
    client, admin_headers, project, other_project, global_results_repo, linked_results_repo, make_task
):
    mine = new_result(client, admin_headers, project, make_task(), global_results_repo)
    assert put_link(client, admin_headers, other_project, global_results_repo, "o").status_code == 201
    theirs = new_result(client, admin_headers, other_project, make_task(project=other_project), global_results_repo)
    assert patch_result(client, admin_headers, other_project, theirs, {"step": "OPENED"}).status_code == 200

    assert [r["id"] for r in client.get(results_url(project), headers=admin_headers).json] == [mine]
    # the step filter is scoped as well
    assert client.get(f"{results_url(project)}?step=OPENED", headers=admin_headers).json == []
    assert [r["id"] for r in client.get(f"{results_url(other_project)}?step=OPENED", headers=admin_headers).json] == [theirs]


def test_get_single_result_and_cross_project_404(
    client, admin_headers, project, other_project, result_id
):
    assert client.get(f"{results_url(project)}/{result_id}", headers=admin_headers).json["id"] == result_id
    assert client.get(f"{results_url(other_project)}/{result_id}", headers=admin_headers).status_code == 404
    assert client.get(f"{results_url(project)}/99999", headers=admin_headers).status_code == 404
    assert client.get(results_url(99999), headers=admin_headers).status_code == 404
    # PATCH from the other project must not change anything
    assert patch_result(client, admin_headers, other_project, result_id, {"step": "MERGED"}).status_code == 404
    assert client.get(f"{results_url(project)}/{result_id}", headers=admin_headers).json["step"] == "UNKNOWN"


def test_task_results_route_lists_the_result(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task = make_task()
    rid = new_result(client, admin_headers, project, task, global_results_repo)
    response = client.get(f"/tasks/{task.id}/results", headers=admin_headers)
    assert response.status_code == 200
    assert [r["id"] for r in response.json] == [rid]
    assert response.json[0]["results_repository_id"] == global_results_repo.id


# ---------------------------------------------------------------- cascades


def test_deleting_task_cascades_to_its_result(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task, keep = make_task(), make_task()
    rid = new_result(client, admin_headers, project, task, global_results_repo)
    kept = new_result(client, admin_headers, project, keep, global_results_repo)

    db.session.delete(task)
    db.session.commit()

    assert client.get(f"{results_url(project)}/{rid}", headers=admin_headers).status_code == 404
    assert [r["id"] for r in client.get(results_url(project), headers=admin_headers).json] == [kept]
    # the link and the repository survive
    assert client.get(link_url(project, global_results_repo), headers=admin_headers).status_code == 200


def test_unlink_refused_while_result_in_progress(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    rid = new_result(client, admin_headers, project, make_task(status="SUCCESS"), global_results_repo)
    set_locked(project)
    response = client.delete(link_url(project, global_results_repo), headers=admin_headers)
    assert response.status_code == 409  # delivery IN_PROGRESS counts as in flight
    assert client.get(f"{results_url(project)}/{rid}", headers=admin_headers).status_code == 200


def test_unlink_refused_while_results_exist_even_when_delivered(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    """Docstring: unlinking is refused while a task delivered to the link (results RESTRICT the link)."""
    task = make_task(status="SUCCESS")
    rid = new_result(client, admin_headers, project, task, global_results_repo)
    assert patch_result(client, admin_headers, project, rid, {"step": "MERGED", "state": "DELIVERED"}).status_code == 200
    set_locked(project)
    response = client.delete(link_url(project, global_results_repo), headers=admin_headers)
    assert response.status_code in (400, 409)
    assert client.get(link_url(project, global_results_repo), headers=admin_headers).status_code == 200
    assert client.get(f"{results_url(project)}/{rid}", headers=admin_headers).status_code == 200


def test_deleting_task_then_unlink_succeeds(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task = make_task(status="SUCCESS")
    new_result(client, admin_headers, project, task, global_results_repo)
    db.session.delete(task)
    db.session.commit()
    set_locked(project)
    assert client.delete(link_url(project, global_results_repo), headers=admin_headers).status_code == 204
    assert client.get(results_url(project), headers=admin_headers).json == []


def test_delete_global_repo_with_results_is_refused(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    rid = new_result(client, admin_headers, project, make_task(status="SUCCESS"), global_results_repo)
    assert patch_result(client, admin_headers, project, rid, {"state": "DELIVERED"}).status_code == 200
    set_locked(project)
    response = client.delete(f"/global/repositories/results/{global_results_repo.id}", headers=admin_headers)
    assert response.status_code in (400, 409)
    assert client.get(f"/global/repositories/results/{global_results_repo.id}", headers=admin_headers).status_code == 200
    assert client.get(f"{results_url(project)}/{rid}", headers=admin_headers).status_code == 200


def test_delete_global_repo_without_results_removes_link(
    client, admin_headers, project, global_results_repo, linked_results_repo
):
    set_locked(project)
    response = client.delete(f"/global/repositories/results/{global_results_repo.id}", headers=admin_headers)
    assert response.status_code == 204
    assert client.get(f"/projects/{project.id}/repositories/results", headers=admin_headers).json == []
    assert client.get(link_url(project, global_results_repo), headers=admin_headers).status_code == 404
