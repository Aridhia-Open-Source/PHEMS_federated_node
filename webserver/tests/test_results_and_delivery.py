"""
Results repositories (link rules, target_dir) and PR results (creation, step/state, filters), ADRs 0006 and 0013.
One test per rule; fixtures come from conftest.
"""
import pytest

from app.helpers.base_model import db
from app.helpers.task_config import build_snapshot, snapshot_hash
from app.models.project import Project
from app.models.project_results_repository import ProjectResultsRepository
from app.models.result import Result
from app.models.task import Task

RESULTS_GLOBAL = "/global/repositories/results"


def link_url(project, repo):
    return f"/projects/{project.id}/repositories/results/{repo.id}"


def trigger_url(project, repo):
    return f"/projects/{project.id}/repositories/triggers/{repo.id}"


def results_url(project):
    return f"/projects/{project.id}/results"


def links(client, admin_headers, project):
    return client.get(f"/projects/{project.id}/repositories/results", headers=admin_headers).json


def set_enabled(project, enabled=True):
    project.enabled = enabled
    db.session.commit()


def switch_link(project, enabled):
    """Flip the project's results link on or off directly."""
    ProjectResultsRepository.query.filter_by(project_id=project.id).one().enabled = enabled
    db.session.commit()


def put_link(client, admin_headers, project, repo, target_dir="results"):
    """Link a results repository (PUT needs the project disabled); returns the response, project left enabled."""
    set_enabled(project, False)
    response = client.put(link_url(project, repo), json={"target_dir": target_dir}, headers=admin_headers)
    set_enabled(project, True)
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


def test_linking_a_results_repository_to_an_enabled_project_is_409(client, admin_headers, project, global_results_repo):
    response = client.put(link_url(project, global_results_repo), json={"target_dir": "results"}, headers=admin_headers)
    assert response.status_code == 409
    assert response.json["error"] == f"Project {project.id} must be disabled to link a results repository"
    assert links(client, admin_headers, project) == []


def test_link_needs_a_disabled_project_then_relink_replaces_settings(
        client, admin_headers, project, global_results_repo):
    url = link_url(project, global_results_repo)
    assert client.put(url, json={"target_dir": "results"}, headers=admin_headers).status_code == 409  # enabled
    assert links(client, admin_headers, project) == []

    set_enabled(project, False)
    response = client.put(url, json={"target_dir": "a", "owned_by_federated_node": False}, headers=admin_headers)
    assert response.status_code == 201 and response.json["project_id"] == project.id

    # PUT replaces: omitted fields go back to their defaults
    response = client.put(url, json={"target_dir": "b"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["target_dir"] == "b" and response.json["owned_by_federated_node"] is True
    assert len(links(client, admin_headers, project)) == 1


def test_relink_target_dir_and_disabling_work_on_an_enabled_project_with_a_task_in_flight(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    make_task()  # a pending task
    url = link_url(project, global_results_repo)
    # the task is pinned to the old target_dir instead
    assert client.put(url, json={"target_dir": "x", "enabled": False}, headers=admin_headers).status_code == 200
    got = client.get(url, headers=admin_headers).json
    assert got["target_dir"] == "x" and got["enabled"] is False


def test_one_results_repo_per_project_but_repo_shared(
    client, admin_headers, project, other_project, global_results_repo, make_results_repo
):
    assert put_link(client, admin_headers, project, global_results_repo).status_code == 201
    second = make_results_repo(uri="github.com/org/second")
    assert put_link(client, admin_headers, project, second, "x").status_code == 409
    assert len(links(client, admin_headers, project)) == 1
    # another project may link the very same global repository
    assert put_link(client, admin_headers, other_project, global_results_repo, "o").status_code == 201


def test_link_target_dir_validation(client, admin_headers, disabled_project, global_results_repo):
    url = link_url(disabled_project, global_results_repo)
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
    assert links(client, admin_headers, disabled_project) == []

    assert client.put(f"/projects/{disabled_project.id}/repositories/results/999", json={"target_dir": "r"},
                      headers=admin_headers).status_code == 404
    assert client.put(f"/projects/999/repositories/results/{global_results_repo.id}", json={"target_dir": "r"},
                      headers=admin_headers).status_code == 404


def test_link_target_dir_normalised_and_never_absolute(client, admin_headers, disabled_project, global_results_repo):
    url = link_url(disabled_project, global_results_repo)
    response = client.put(url, json={"target_dir": "/etc/out/"}, headers=admin_headers)
    assert response.status_code == 201 and response.json["target_dir"] == "etc/out"
    response = client.put(url, json={"target_dir": "./a//b/./c/"}, headers=admin_headers)
    assert response.status_code == 200
    assert client.get(url, headers=admin_headers).json["target_dir"] == "a/b/c"


def test_patch_link_settings(client, admin_headers, project, global_results_repo, linked_results_repo):
    url = link_url(project, global_results_repo)
    response = client.patch(url, json={"target_dir": "/new//dir/"}, headers=admin_headers)
    assert response.status_code == 200 and response.json["target_dir"] == "new/dir"
    for body in ({"target_dir": "../up"}, {"target_dir": ""}, {"bogus": 1}, {}, {"enabled": "no"}):
        assert client.patch(url, json=body, headers=admin_headers).status_code == 400, body
    assert client.get(url, headers=admin_headers).json["target_dir"] == "new/dir"


# ---------------------------------------------------------------- loop refusal (results dir vs watched dir)


def test_results_dir_inside_watched_dir_refused(
    client, admin_headers, disabled_project, make_trigger_repo, make_results_repo
):
    """A results target_dir that overlaps a watched dir of the same git repository would loop."""
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    assert client.put(trigger_url(disabled_project, trigger), json={"watch_dir": "/triggers/in/"},
                      headers=admin_headers).status_code == 201

    for target in ("triggers/in/out", "triggers/in", "triggers", "./triggers//in/x"):  # inside, equal, parent, unnormalised
        response = client.put(link_url(disabled_project, results), json={"target_dir": target}, headers=admin_headers)
        assert response.status_code == 400, target
        assert "overlap" in response.json["error"]
    assert links(client, admin_headers, disabled_project) == []

    response = client.put(link_url(disabled_project, results), json={"target_dir": "triggers/out"}, headers=admin_headers)
    assert response.status_code == 201  # a sibling dir is fine

    # PATCHing the target_dir into the watched dir is refused and rolled back
    assert client.patch(link_url(disabled_project, results), json={"target_dir": "triggers/in/x"},
                        headers=admin_headers).status_code == 400
    assert client.get(link_url(disabled_project, results), headers=admin_headers).json["target_dir"] == "triggers/out"


def test_watch_dir_over_results_dir_refused_and_other_repo_or_project(
    client, admin_headers, project, other_project, make_trigger_repo, make_results_repo
):
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    elsewhere = make_trigger_repo(uri="github.com/org/elsewhere")
    assert put_link(client, admin_headers, project, results, "out/data").status_code == 201

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


def test_unlink_then_another_repo_can_be_linked(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_results_repo
):
    url = link_url(project, global_results_repo)
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).status_code == 404
    assert client.delete(url, headers=admin_headers).status_code == 404
    assert links(client, admin_headers, project) == []

    other = make_results_repo(uri="github.com/org/replacement")
    assert put_link(client, admin_headers, project, other, "r").status_code == 201


def test_unlink_and_global_delete_work_with_results_and_tasks_in_flight(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    """A delete never needs a drain, delivered results or not: the rows are only marked deleted."""
    rid = new_result(client, admin_headers, project, make_task(), global_results_repo)
    assert patch_result(client, admin_headers, project, rid, {"step": "MERGED", "state": "DELIVERED"}).status_code == 200
    make_task()  # in flight
    url = link_url(project, global_results_repo)
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).status_code == 404
    assert get_result(client, admin_headers, project, rid)["step"] == "MERGED"  # its result is still readable
    assert put_link(client, admin_headers, project, global_results_repo).status_code == 201
    assert client.delete(f"{RESULTS_GLOBAL}/{global_results_repo.id}?force=true", headers=admin_headers).status_code == 204


def test_a_reference_to_a_deleted_link_still_loads_but_lists_and_gets_hide_it(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    rid = new_result(client, admin_headers, project, make_task(), global_results_repo)
    url = link_url(project, global_results_repo)
    assert client.delete(url, headers=admin_headers).status_code == 204
    db.session.expire_all()
    result = db.session.get(Result, rid)
    assert result.assignment is not None and result.assignment.deleted_at is not None  # (a) many-to-one
    assert result.assignment.results_repository is not None
    assert db.session.get(Project, project.id).results_repository_assignments == []  # (b) collection
    assert client.get(url, headers=admin_headers).status_code == 404  # (c) the API
    assert links(client, admin_headers, project) == []


def test_a_forced_global_delete_deletes_the_links_and_history_still_loads_them(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    rid = new_result(client, admin_headers, project, make_task(), global_results_repo)
    url = f"{RESULTS_GLOBAL}/{global_results_repo.id}"
    refused = client.delete(url, headers=admin_headers)
    assert refused.status_code == 409 and refused.json["details"] == [{"id": project.id, "name": project.name}]
    assert client.delete(f"{url}?force=true", headers=admin_headers).status_code == 204
    assert client.get(link_url(project, global_results_repo), headers=admin_headers).status_code == 404
    assert links(client, admin_headers, project) == []
    db.session.expire_all()
    link = db.session.get(Result, rid).assignment
    assert link.deleted_at is not None and link.revoked is True
    assert link.results_repository.deleted_at is not None  # loaded through the references, never None


def test_delivery_of_a_task_in_flight_when_its_link_is_deleted_gives_a_final_revoked_result(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task = make_task(status="SUCCESS")
    assert client.delete(link_url(project, global_results_repo), headers=admin_headers).status_code == 204
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 201, response.json
    assert (response.json["step"], response.json["state"]) == ("REVOKED", "FAILED")
    again = post_result(client, admin_headers, project, task, global_results_repo)  # idempotent
    assert again.status_code == 200 and again.json["id"] == response.json["id"]
    assert get_result(client, admin_headers, project, response.json["id"])["step"] == "REVOKED"


def test_delivery_of_a_task_in_flight_when_the_global_repository_is_deleted_gives_a_revoked_result(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task = make_task(status="SUCCESS")
    assert client.delete(f"{RESULTS_GLOBAL}/{global_results_repo.id}?force=true", headers=admin_headers).status_code == 204
    assert client.get(f"{RESULTS_GLOBAL}/{global_results_repo.id}", headers=admin_headers).status_code == 404
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 201 and response.json["step"] == "REVOKED"


def test_delivery_for_a_deleted_project_is_a_404(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    task = make_task(status="SUCCESS")
    assert client.delete(f"/projects/{project.id}", headers=admin_headers).status_code == 204
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code == 404
    assert client.get(f"/projects/{project.id}/tasks/{task.id}/config", headers=admin_headers).status_code == 404


def test_global_delete_removes_the_link(
    client, admin_headers, project, global_results_repo, linked_results_repo
):
    assert client.delete(f"{RESULTS_GLOBAL}/{global_results_repo.id}?force=true", headers=admin_headers).status_code == 204
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
    assert patch_result(client, admin_headers, project, created.json["id"], {"step": "PUSHED"}).status_code == 409
    # un-revoking the link does not deliver it
    assert client.patch(link_url(project, global_results_repo), json={"revoked": False}, headers=admin_headers).status_code == 200
    assert get_result(client, admin_headers, project, created.json["id"])["step"] == "REVOKED"


def pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo):
    """A SUCCESS task made from a pull request, on the project's dataset, with its results link."""
    created = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert created.status_code == 201, created.json
    task = db.session.get(Task, created.json["id"])
    assert task.spec.dataset_id is not None
    assert client.patch(f"/projects/{project.id}/tasks/{task.id}", json={"status": "SUCCESS"}, headers=admin_headers).status_code == 200
    return task


def test_post_result_is_revoked_when_the_trigger_link_is_revoked(
    client, admin_headers, project, global_results_repo, global_trigger_repo, pr_trigger, spec_raw, linked_dataset,
    linked_results_repo
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    assert client.patch(trigger_url(project, global_trigger_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 201, response.json
    assert (response.json["step"], response.json["state"]) == ("REVOKED", "FAILED")
    assert response.json["error"] == f"revoked: trigger repository {global_trigger_repo.repo_path}"
    # final, and a second post returns it
    assert patch_result(client, admin_headers, project, response.json["id"], {"step": "PUSHED"}).status_code == 409
    again = post_result(client, admin_headers, project, task, global_results_repo)
    assert again.status_code == 200 and again.json["id"] == response.json["id"]


@pytest.mark.parametrize("how", ["revoked", "deleted"])
def test_post_result_is_revoked_when_the_dataset_link_is_revoked_or_deleted(
    client, admin_headers, project, global_results_repo, global_dataset, pr_trigger, spec_raw, linked_dataset,
    linked_results_repo, how
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    url = f"/projects/{project.id}/datasets/{global_dataset.id}"
    if how == "revoked":
        assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    else:
        assert client.delete(url, headers=admin_headers).status_code == 204
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 201, response.json
    assert (response.json["step"], response.json["state"]) == ("REVOKED", "FAILED")
    assert response.json["error"] == f"revoked: dataset {global_dataset.name}"


def test_post_result_names_every_revoked_resource(
    client, admin_headers, project, global_results_repo, global_dataset, global_trigger_repo, pr_trigger, spec_raw,
    linked_dataset, linked_results_repo
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    assert client.patch(trigger_url(project, global_trigger_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    assert client.patch(f"/projects/{project.id}/datasets/{global_dataset.id}", json={"revoked": True}, headers=admin_headers).status_code == 200
    assert client.patch(link_url(project, global_results_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.json["step"] == "REVOKED"
    assert response.json["error"] == (
        f"revoked: trigger repository {global_trigger_repo.repo_path}; dataset {global_dataset.name}; "
        f"results repository {global_results_repo.repo_path}"
    )


@pytest.mark.parametrize("kind", ["project", "trigger", "dataset", "results", "provider"])
def test_post_result_is_revoked_when_a_global_resource_provider_or_project_is_revoked(
    client, admin_headers, project, global_results_repo, global_dataset, global_trigger_repo, pr_trigger, spec_raw,
    linked_dataset, linked_results_repo, kind
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    provider = global_trigger_repo.provider
    url, name = {
        "project": (f"/projects/{project.id}", f"project {project.name}"),
        "trigger": (f"/global/repositories/triggers/{global_trigger_repo.id}",
                    f"trigger repository {global_trigger_repo.repo_path}"),
        "dataset": (f"/global/datasets/{global_dataset.id}", f"dataset {global_dataset.name}"),
        "results": (f"{RESULTS_GLOBAL}/{global_results_repo.id}", f"results repository {global_results_repo.repo_path}"),
        "provider": (f"/global/providers/{provider.id}", f"provider {provider.name}"),
    }[kind]
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200

    response = post_result(client, admin_headers, project, task, global_results_repo)

    assert response.status_code == 201, response.json
    assert (response.json["step"], response.json["state"]) == ("REVOKED", "FAILED")
    assert response.json["error"] == f"revoked: {name} (revoked)"
    # final, and a second post returns it
    assert patch_result(client, admin_headers, project, response.json["id"], {"step": "PUSHED"}).status_code == 409


def test_post_result_is_revoked_for_a_link_created_after_the_global_resource_was_revoked(
    client, admin_headers, project, global_results_repo, global_dataset, make_task
):
    for url in (f"{RESULTS_GLOBAL}/{global_results_repo.id}", f"/global/datasets/{global_dataset.id}"):
        assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    assert put_link(client, admin_headers, project, global_results_repo).status_code == 201
    dataset_link = client.put(f"/projects/{project.id}/datasets/{global_dataset.id}", json={}, headers=admin_headers)
    assert dataset_link.status_code == 201
    assert (dataset_link.json["revoked"], dataset_link.json["active"]) == (False, False)
    task = make_task(dataset_id=global_dataset.id)
    assert client.patch(f"/projects/{project.id}/tasks/{task.id}", json={"status": "SUCCESS"}, headers=admin_headers).status_code == 200

    response = post_result(client, admin_headers, project, task, global_results_repo)

    assert response.status_code == 201, response.json
    assert (response.json["step"], response.json["state"]) == ("REVOKED", "FAILED")
    assert response.json["error"] == (
        f"revoked: dataset {global_dataset.name} (revoked); "
        f"results repository {global_results_repo.repo_path} (revoked)"
    )


def test_post_result_is_revoked_for_a_repository_linked_after_its_provider_was_revoked(
    client, admin_headers, project, global_results_repo, make_task
):
    provider = global_results_repo.provider
    assert client.patch(f"/global/providers/{provider.id}", json={"revoked": True}, headers=admin_headers).status_code == 200
    assert put_link(client, admin_headers, project, global_results_repo).status_code == 201
    task = make_task()
    assert client.patch(f"/projects/{project.id}/tasks/{task.id}", json={"status": "SUCCESS"}, headers=admin_headers).status_code == 200

    response = post_result(client, admin_headers, project, task, global_results_repo)

    assert response.status_code == 201, response.json
    assert (response.json["step"], response.json["error"]) == ("REVOKED", f"revoked: provider {provider.name} (revoked)")


def test_post_result_is_not_revoked_when_the_trigger_and_dataset_links_are_only_switched_off(
    client, admin_headers, project, global_results_repo, global_dataset, global_trigger_repo, pr_trigger, spec_raw,
    linked_dataset, linked_results_repo
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    assert client.patch(trigger_url(project, global_trigger_repo), json={"enabled": False}, headers=admin_headers).status_code == 200
    assert client.patch(f"/projects/{project.id}/datasets/{global_dataset.id}", json={"enabled": False}, headers=admin_headers).status_code == 200
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 201, response.json
    assert (response.json["step"], response.json["state"]) == ("UNKNOWN", "IN_PROGRESS")


def revoke_urls(project, global_results_repo, global_dataset, global_trigger_repo):
    """What can be revoked after a result exists: kind -> (url, the name revoked_resources gives it)."""
    return {
        "trigger link": (trigger_url(project, global_trigger_repo), f"trigger repository {global_trigger_repo.repo_path}"),
        "dataset link": (f"/projects/{project.id}/datasets/{global_dataset.id}", f"dataset {global_dataset.name}"),
        "results link": (link_url(project, global_results_repo), f"results repository {global_results_repo.repo_path}"),
        "project": (f"/projects/{project.id}", f"project {project.name} (revoked)"),
        "global trigger": (f"/global/repositories/triggers/{global_trigger_repo.id}",
                           f"trigger repository {global_trigger_repo.repo_path} (revoked)"),
        "global dataset": (f"/global/datasets/{global_dataset.id}", f"dataset {global_dataset.name} (revoked)"),
        "global results": (f"{RESULTS_GLOBAL}/{global_results_repo.id}",
                           f"results repository {global_results_repo.repo_path} (revoked)"),
    }


def held_result(client, admin_headers, project, task, repo):
    """A result recorded while the results link was switched off: UNKNOWN and FAILED, waiting for the link."""
    switch_link(project, False)
    created = post_result(client, admin_headers, project, task, repo)
    assert created.status_code == 201, created.json
    assert (created.json["step"], created.json["state"]) == ("UNKNOWN", "FAILED")
    return created.json["id"]


@pytest.mark.parametrize("kind", [
    "trigger link", "dataset link", "results link", "project", "global trigger", "global dataset", "global results"
])
def test_post_result_revokes_an_existing_held_result_when_something_is_revoked_later(
    client, admin_headers, project, global_results_repo, global_dataset, global_trigger_repo, pr_trigger, spec_raw,
    linked_dataset, linked_results_repo, kind
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    rid = held_result(client, admin_headers, project, task, global_results_repo)
    url, name = revoke_urls(project, global_results_repo, global_dataset, global_trigger_repo)[kind]
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200

    again = post_result(client, admin_headers, project, task, global_results_repo)

    assert again.status_code == 200, again.json
    assert (again.json["id"], again.json["step"], again.json["state"]) == (rid, "REVOKED", "FAILED")
    assert again.json["error"] == f"revoked: {name}"
    assert get_result(client, admin_headers, project, rid)["step"] == "REVOKED"
    # final: the delivery cannot move it, and the retry sensor's FAILED, non-final query no longer finds it
    assert patch_result(client, admin_headers, project, rid, {"step": "PUSHED"}).status_code == 409
    assert patch_result(client, admin_headers, project, rid, {"step": "OPENED"}).status_code == 409


@pytest.mark.parametrize("step, state", [
    ("UNKNOWN", "IN_PROGRESS"), ("UNKNOWN", "FAILED"), ("PUSHED", "IN_PROGRESS"), ("PUSHED", "FAILED")
])
def test_post_result_revokes_an_existing_result_from_each_non_final_step_and_state(
    client, admin_headers, project, global_results_repo, global_trigger_repo, pr_trigger, spec_raw,
    linked_dataset, linked_results_repo, step, state
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    rid = new_result(client, admin_headers, project, task, global_results_repo)
    assert patch_result(client, admin_headers, project, rid, {"step": step, "state": state, "error": "boom"}).status_code == 200
    assert client.patch(trigger_url(project, global_trigger_repo), json={"revoked": True}, headers=admin_headers).status_code == 200

    again = post_result(client, admin_headers, project, task, global_results_repo)

    assert again.status_code == 200, again.json
    assert (again.json["id"], again.json["step"], again.json["state"]) == (rid, "REVOKED", "FAILED")
    assert again.json["error"] == f"revoked: trigger repository {global_trigger_repo.repo_path}"


def test_post_result_returns_an_existing_result_unchanged_when_nothing_is_revoked(
    client, admin_headers, project, global_results_repo, global_trigger_repo, pr_trigger, spec_raw,
    linked_dataset, linked_results_repo
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    rid = held_result(client, admin_headers, project, task, global_results_repo)
    # switched off is not revoked
    assert client.patch(trigger_url(project, global_trigger_repo), json={"enabled": False}, headers=admin_headers).status_code == 200
    before = get_result(client, admin_headers, project, rid)

    again = post_result(client, admin_headers, project, task, global_results_repo)

    assert again.status_code == 200 and again.json == before
    assert (before["step"], before["state"], before["error"]) == ("UNKNOWN", "FAILED", "results link switched off")


@pytest.mark.parametrize("step", ["OPENED", "MERGED", "CLOSED"])
def test_post_result_returns_an_existing_final_result_unchanged_even_if_something_is_revoked_now(
    client, admin_headers, project, global_results_repo, global_trigger_repo, pr_trigger, spec_raw,
    linked_dataset, linked_results_repo, step
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    rid = new_result(client, admin_headers, project, task, global_results_repo)
    assert patch_result(client, admin_headers, project, rid, {"step": step, "state": "DELIVERED"}).status_code == 200
    before = get_result(client, admin_headers, project, rid)
    assert client.patch(trigger_url(project, global_trigger_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    assert client.patch(f"/projects/{project.id}", json={"revoked": True}, headers=admin_headers).status_code == 200

    again = post_result(client, admin_headers, project, task, global_results_repo)

    assert again.status_code == 200 and again.json == before
    assert (again.json["step"], again.json["state"]) == (step, "DELIVERED")


def test_post_result_keeps_the_error_of_an_existing_revoked_result(
    client, admin_headers, project, global_results_repo, global_dataset, global_trigger_repo, pr_trigger, spec_raw,
    linked_dataset, linked_results_repo
):
    task = pr_task_in_flight(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo)
    assert client.patch(trigger_url(project, global_trigger_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    created = post_result(client, admin_headers, project, task, global_results_repo)
    assert created.status_code == 201 and created.json["step"] == "REVOKED"
    assert client.patch(f"/projects/{project.id}/datasets/{global_dataset.id}", json={"revoked": True}, headers=admin_headers).status_code == 200

    again = post_result(client, admin_headers, project, task, global_results_repo)

    assert again.status_code == 200 and again.json == created.json
    assert again.json["error"] == f"revoked: trigger repository {global_trigger_repo.repo_path}"


# ---------------------------------------------------------------- PATCH /results/<id>


def test_step_is_forward_only(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    def fresh():
        return new_result(client, admin_headers, project, make_task(), global_results_repo)

    rid = fresh()
    for step in ("PUSHED", "OPENED", "OPENED", "MERGED"):  # forward, same step again is allowed
        assert patch_result(client, admin_headers, project, rid, {"step": step}).json["step"] == step
    for backwards in ("OPENED", "UNKNOWN", "CLOSED", "REVOKED", "STALE"):  # MERGED, CLOSED, REVOKED and STALE are terminal siblings
        assert patch_result(client, admin_headers, project, rid, {"step": backwards}).status_code == 409
    assert get_result(client, admin_headers, project, rid)["step"] == "MERGED"

    rid = fresh()  # steps may be skipped
    assert patch_result(client, admin_headers, project, rid, {"step": "CLOSED"}).status_code == 200
    assert patch_result(client, admin_headers, project, rid, {"step": "PUSHED"}).status_code == 409


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


def test_list_filter_by_state(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    ids = {}
    for state, step in (("IN_PROGRESS", "UNKNOWN"), ("FAILED", "PUSHED"), ("FAILED", "OPENED"), ("DELIVERED", "OPENED")):
        ids[(state, step)] = new_result(client, admin_headers, project, make_task(), global_results_repo)
        if step != "UNKNOWN":
            body = {"step": step, "state": state}
            assert patch_result(client, admin_headers, project, ids[(state, step)], body).status_code == 200
    url = results_url(project)

    def listed(query):
        response = client.get(f"{url}{query}", headers=admin_headers)
        assert response.status_code == 200
        return [r["id"] for r in response.json]

    assert listed("?state=FAILED") == [ids[("FAILED", "PUSHED")], ids[("FAILED", "OPENED")]]
    assert listed("?state=FAILED&step=PUSHED") == [ids[("FAILED", "PUSHED")]]
    assert listed("?state=DELIVERED") == [ids[("DELIVERED", "OPENED")]]
    for query in ("?state=NOPE", "?state=failed"):
        assert client.get(f"{url}{query}", headers=admin_headers).status_code == 400, query



def test_list_filter_by_active_link(client, admin_headers, project, global_results_repo, linked_results_repo, make_task):
    rid = new_result(client, admin_headers, project, make_task(), global_results_repo)
    assert patch_result(client, admin_headers, project, rid, {"step": "PUSHED", "state": "FAILED"}).status_code == 200
    url = f"{results_url(project)}?state=FAILED&active_link=true"
    link = link_url(project, global_results_repo)

    assert [r["id"] for r in client.get(url, headers=admin_headers).json] == [rid]
    for switch_off, switch_on in (
        (lambda: client.patch(link, json={"revoked": True}, headers=admin_headers),
         lambda: client.patch(link, json={"revoked": False}, headers=admin_headers)),
        (lambda: switch_link(project, False), lambda: switch_link(project, True)),
    ):
        switch_off()
        assert client.get(url, headers=admin_headers).json == []
        # without the filter the result is still listed
        assert [r["id"] for r in client.get(f"{results_url(project)}?state=FAILED", headers=admin_headers).json] == [rid]
        switch_on()
    assert [r["id"] for r in client.get(url, headers=admin_headers).json] == [rid]


def test_post_result_through_a_switched_off_link_is_failed_and_waits(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task = make_task()
    assert client.patch(f"/projects/{project.id}/tasks/{task.id}", json={"status": "SUCCESS"}, headers=admin_headers).status_code == 200
    switch_link(project, False)

    created = post_result(client, admin_headers, project, task, global_results_repo)

    assert created.status_code == 201
    assert (created.json["step"], created.json["state"], created.json["error"]) == (
        "UNKNOWN", "FAILED", "results link switched off"
    )
    assert post_result(client, admin_headers, project, task, global_results_repo).json["id"] == created.json["id"]
    assert client.get(f"{results_url(project)}?state=FAILED&active_link=true", headers=admin_headers).json == []


def switch_off(client, admin_headers, project, global_results_repo, how):
    """Switch the results link off at the link, the global repository or the repository's provider."""
    if how == "link":
        switch_link(project, False)
        return
    url = {"repository": f"{RESULTS_GLOBAL}/{global_results_repo.id}",
           "provider": f"/global/providers/{global_results_repo.provider_id}"}[how]
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 200


def switch_on(client, admin_headers, project, global_results_repo, how):
    if how == "link":
        switch_link(project, True)
        return
    url = {"repository": f"{RESULTS_GLOBAL}/{global_results_repo.id}",
           "provider": f"/global/providers/{global_results_repo.provider_id}"}[how]
    assert client.patch(url, json={"enabled": True}, headers=admin_headers).status_code == 200


@pytest.mark.parametrize("how", ["repository", "provider"])
def test_post_result_through_a_switched_off_global_repository_or_provider_is_failed_and_waits(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task, how
):
    task = make_task(status="SUCCESS")
    switch_off(client, admin_headers, project, global_results_repo, how)
    listed = f"{results_url(project)}?state=FAILED"

    created = post_result(client, admin_headers, project, task, global_results_repo)

    assert created.status_code == 201, created.json
    assert (created.json["step"], created.json["state"], created.json["error"]) == (
        "UNKNOWN", "FAILED", "results link switched off"
    )
    rid = created.json["id"]
    assert post_result(client, admin_headers, project, task, global_results_repo).json["id"] == rid
    # held, not delivered: the active_link filter leaves it out while the link is off, and takes it back once it is on
    assert [r["id"] for r in client.get(listed, headers=admin_headers).json] == [rid]
    assert client.get(f"{listed}&active_link=true", headers=admin_headers).json == []
    switch_on(client, admin_headers, project, global_results_repo, how)
    assert [r["id"] for r in client.get(f"{listed}&active_link=true", headers=admin_headers).json] == [rid]
    assert get_result(client, admin_headers, project, rid)["step"] == "UNKNOWN"


def test_post_result_checks_a_success_task_before_anything_is_revoked(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task = make_task()  # PENDING
    assert client.patch(link_url(project, global_results_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    assert post_result(client, admin_headers, project, task, global_results_repo).status_code == 409
    assert client.get(results_url(project), headers=admin_headers).json == []


def test_post_result_revoked_beats_switched_off(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task
):
    task = make_task(status="SUCCESS")
    switch_link(project, False)
    assert client.patch(link_url(project, global_results_repo), json={"revoked": True}, headers=admin_headers).status_code == 200
    created = post_result(client, admin_headers, project, task, global_results_repo)
    assert created.status_code == 201
    assert (created.json["step"], created.json["state"]) == ("REVOKED", "FAILED")


@pytest.mark.parametrize("how", ["link", "repository", "provider"])
def test_post_result_stale_beats_switched_off_and_is_final(
    client, admin_headers, project, global_results_repo, linked_results_repo, make_task, how
):
    snapshot = build_snapshot(project, None)
    task = make_task(status="SUCCESS", config_snapshot=snapshot, config_hash=snapshot_hash(snapshot))
    assert client.patch(link_url(project, global_results_repo), json={"target_dir": "out"}, headers=admin_headers).status_code == 200
    switch_off(client, admin_headers, project, global_results_repo, how)

    created = post_result(client, admin_headers, project, task, global_results_repo)

    assert created.status_code == 201, created.json
    assert (created.json["step"], created.json["state"]) == ("STALE", "FAILED")
    assert created.json["error"].startswith("task configuration changed since the task was created: ")
    rid = created.json["id"]
    # final: switching the link back on does not deliver it, and a second post returns it
    switch_on(client, admin_headers, project, global_results_repo, how)
    again = post_result(client, admin_headers, project, task, global_results_repo)
    assert again.status_code == 200 and again.json["id"] == rid and again.json["step"] == "STALE"
    assert patch_result(client, admin_headers, project, rid, {"step": "PUSHED"}).status_code == 409


def test_patching_a_result_to_failed_leaves_its_step_alone(client, admin_headers, project, result_id):
    """State and step are separate columns (ADR 0004): a failed delivery keeps the step it reached."""
    assert patch_result(client, admin_headers, project, result_id, {"step": "PUSHED"}).status_code == 200
    response = patch_result(client, admin_headers, project, result_id,
                            {"state": "FAILED", "error": "push rejected", "attempts": 2})
    assert response.status_code == 200, response.json
    assert (response.json["step"], response.json["state"], response.json["error"], response.json["attempts"]) == (
        "PUSHED", "FAILED", "push rejected", 2
    )
    assert get_result(client, admin_headers, project, result_id)["step"] == "PUSHED"


# ---------------------------------------------------------------- loop refusal: a trigger watching the whole repository


def test_whole_repository_trigger_then_results_link_in_the_same_repository_is_refused(
    client, admin_headers, disabled_project, make_trigger_repo, make_results_repo
):
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    assert client.put(trigger_url(disabled_project, trigger), json={"watch_dir": ""},
                      headers=admin_headers).status_code == 201

    response = client.put(link_url(disabled_project, results), json={"target_dir": "out"}, headers=admin_headers)

    assert response.status_code == 400, response.json
    assert "watches the whole repository" in response.json["error"]
    assert links(client, admin_headers, disabled_project) == []


def test_results_link_then_whole_repository_trigger_in_the_same_repository_is_refused(
    client, admin_headers, project, make_trigger_repo, make_results_repo
):
    trigger = make_trigger_repo(uri="github.com/org/shared")
    results = make_results_repo(uri="github.com/org/shared")
    assert put_link(client, admin_headers, project, results, "out").status_code == 201

    response = client.put(trigger_url(project, trigger), json={"watch_dir": ""}, headers=admin_headers)

    assert response.status_code == 400, response.json
    assert "watches the whole repository" in response.json["error"]
    assert client.get(trigger_url(project, trigger), headers=admin_headers).status_code == 404
