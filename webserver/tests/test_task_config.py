"""
A task is pinned to the configuration it was created under (helpers/task_config): the snapshot and its
diff, where it is set, the check endpoint, and the publish gate (STALE result).
"""
import pytest

from app.helpers.base_model import db
from app.helpers.task_config import build_snapshot, config_changes, diff, snapshot_hash
from app.models.task import Task

RESULTS = {"repository": "https://github.com/org/results-global", "api_uri": "https://api.github.com",
           "target_dir": "results/"}
DATASET = {"name": "ds", "host": "h", "port": 5432, "type": "postgres", "read_schema": None, "write_schema": None}


def snapshot(**fields) -> dict:
    return {"version": 1, "results": dict(RESULTS), "dataset": dict(DATASET), **fields}


# --------------------------------------------------------------------------- pure functions


def test_hash_is_stable_and_follows_content():
    a, b = snapshot(), snapshot()
    b_reordered = dict(reversed(list(b.items())))
    assert snapshot_hash(a) == snapshot_hash(b_reordered) and len(snapshot_hash(a)) == 64
    changed = snapshot(results={**RESULTS, "target_dir": "out/"})
    assert snapshot_hash(changed) != snapshot_hash(a)


def test_diff_lists_changed_fields_readably():
    current = snapshot(results={**RESULTS, "target_dir": "out/"}, dataset={**DATASET, "port": 1})
    assert diff(snapshot(), current) == ["results.target_dir: 'results/' -> 'out/'", "dataset.port: 5432 -> 1"]
    assert diff(snapshot(), snapshot()) == []


def test_diff_results_or_dataset_added_or_removed():
    assert diff(snapshot(results=None), snapshot()) == [f"results: None -> {RESULTS!r}"]
    assert diff(snapshot(), snapshot(dataset=None)) == [f"dataset: {DATASET!r} -> None"]


def test_diff_ignores_version_and_fields_the_stored_snapshot_lacks():
    assert diff(snapshot(version=1), snapshot(version=2)) == []
    stored = snapshot()
    del stored["dataset"]
    # a field added in a later version is unchanged
    assert diff(stored, snapshot(dataset={**DATASET, "name": "other"})) == []
    stored["results"].pop("api_uri")
    assert diff(stored, snapshot()) == []


def test_task_without_a_snapshot_has_no_changes(project, make_task):
    task = make_task()
    assert task.config_snapshot is None and config_changes(task) == []


# --------------------------------------------------------------------------- the snapshot


def test_build_snapshot_of_a_project_with_nothing(project):
    assert build_snapshot(project, None) == {"version": 1, "results": None, "dataset": None}


def test_build_snapshot_holds_identity_fields_only(project, global_results_repo, linked_results_repo, global_dataset):
    snap = build_snapshot(project, global_dataset)
    assert snap["results"] == {
        "repository_id": global_results_repo.id, "repository": global_results_repo.uri, "api_uri": global_results_repo.provider.api_uri,
        "target_dir": "results",
    }
    assert snap["dataset"] == {
        "name": global_dataset.name, "host": global_dataset.host, "port": global_dataset.port,
        "type": global_dataset.type, "read_schema": global_dataset.read_schema,
        "write_schema": global_dataset.write_schema,
    }
    text = str(snap).lower()
    assert "secret" not in text and "enabled" not in text and "revoked" not in text


# --------------------------------------------------------------------------- set at creation


def reload_task(task_id) -> Task:
    return db.session.get(Task, task_id)


def test_pr_task_is_pinned_at_creation_and_retry_does_not_repin(
        client, admin_headers, project, pr_trigger, spec_raw, linked_results_repo, global_results_repo):
    created = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert created.status_code == 201, created.json
    task = reload_task(created.json["id"])
    assert task.config_snapshot["results"]["target_dir"] == "results"
    assert task.config_hash == snapshot_hash(task.config_snapshot)
    assert created.json["config_hash"] == task.config_hash and "config_snapshot" not in created.json

    url = f"/projects/{project.id}/repositories/results/{global_results_repo.id}"
    assert client.patch(url, json={"target_dir": "out"}, headers=admin_headers).status_code == 200
    tasks = f"/projects/{project.id}/tasks/{task.id}"
    assert client.patch(tasks, json={"status": "FAILED"}, headers=admin_headers).status_code == 200
    assert client.post(f"{tasks}/retry", json={}, headers=admin_headers).status_code == 200
    db.session.expire_all()
    task = reload_task(task.id)
    assert task.config_snapshot["results"]["target_dir"] == "results"
    assert task.config_hash == created.json["config_hash"]


# The task created through POST /projects/<id>/tasks is covered by TestPostTasks in tasks/test_task_from_spec.py


# --------------------------------------------------------------------------- check endpoint and publish gate


def pinned_task(project, make_task, dataset=None):
    snap = build_snapshot(project, dataset)
    fields = {"dataset_id": dataset.id} if dataset else {}
    return make_task(config_snapshot=snap, config_hash=snapshot_hash(snap), **fields)


def config_url(project, task):
    return f"/projects/{project.id}/tasks/{task.id}/config"


def set_target_dir(client, admin_headers, project, repo, target_dir):
    url = f"/projects/{project.id}/repositories/results/{repo.id}"
    response = client.patch(url, json={"target_dir": target_dir}, headers=admin_headers)
    assert response.status_code == 200, response.json


def test_config_is_current_then_stale_after_target_dir_changes(
        client, admin_headers, project, linked_results_repo, global_results_repo, make_task):
    task = pinned_task(project, make_task)
    current = client.get(config_url(project, task), headers=admin_headers)
    assert current.status_code == 200
    assert current.json == {
        "outcome": "launch", "cause": None, "current": True, "changes": [], "config_hash": task.config_hash, "config_snapshot": task.config_snapshot,
        "revoked": [],
    }
    assert current.json["config_snapshot"]["results"]["target_dir"] == "results"

    set_target_dir(client, admin_headers, project, global_results_repo, "out")
    stale = client.get(config_url(project, task), headers=admin_headers)
    assert stale.status_code == 200
    assert stale.json["current"] is False and stale.json["config_hash"] == task.config_hash
    assert stale.json["changes"] == ["results.target_dir: 'results' -> 'out'"]
    assert stale.json["outcome"] == "fail"
    assert stale.json["cause"] == (
        "task configuration changed since the task was created: results.target_dir: 'results' -> 'out'")


def test_config_of_a_task_without_a_snapshot_is_current(client, admin_headers, project, make_task):
    task = make_task()
    assert client.get(config_url(project, task), headers=admin_headers).json == {
        "outcome": "launch", "cause": None, "current": True, "changes": [], "config_hash": None,
        "config_snapshot": None, "revoked": []}


def test_config_404_for_a_task_of_another_project(client, admin_headers, project, other_project, make_task):
    task = make_task(project=other_project)
    assert client.get(config_url(project, task), headers=admin_headers).status_code == 404
    assert client.get(f"/projects/{project.id}/tasks/9999/config", headers=admin_headers).status_code == 404


def test_dataset_change_makes_the_task_stale(
        client, admin_headers, project, linked_results_repo, linked_dataset, global_dataset, make_task):
    task = pinned_task(project, make_task, dataset=global_dataset)
    old_host = global_dataset.host
    assert client.get(config_url(project, task), headers=admin_headers).json["current"] is True
    assert client.patch(f"/global/datasets/{global_dataset.id}", json={"host": "elsewhere"},
                        headers=admin_headers).status_code == 200
    changes = client.get(config_url(project, task), headers=admin_headers).json["changes"]
    assert changes == [f"dataset.host: {old_host!r} -> 'elsewhere'"]


def post_result(client, admin_headers, project, task, repo):
    return client.post(f"/projects/{project.id}/results",
                       json={"task_id": task.id, "results_repository_id": repo.id}, headers=admin_headers)


def test_post_result_is_stale_when_the_target_dir_changed_after_creation(
        client, admin_headers, project, linked_results_repo, global_results_repo, make_task):
    task = pinned_task(project, make_task)
    set_target_dir(client, admin_headers, project, global_results_repo, "out")
    task.status = "SUCCESS"
    db.session.commit()

    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 201, response.json
    assert response.json["step"] == "STALE" and response.json["state"] == "FAILED"
    assert response.json["error"].startswith("task configuration changed since the task was created: ")
    assert "results.target_dir" in response.json["error"]
    # final: it can not move, and a second post returns it
    patched = client.patch(f"/projects/{project.id}/results/{response.json['id']}", json={"step": "OPENED"},
                           headers=admin_headers)
    assert patched.status_code == 409
    again = post_result(client, admin_headers, project, task, global_results_repo)
    assert again.status_code == 200 and again.json["id"] == response.json["id"]


def test_post_result_of_a_current_task_is_not_stale(
        client, admin_headers, project, linked_results_repo, global_results_repo, make_task):
    task = pinned_task(project, make_task)
    task.status = "SUCCESS"
    db.session.commit()
    response = post_result(client, admin_headers, project, task, global_results_repo)
    assert response.status_code == 201 and response.json["step"] == "UNKNOWN"


def test_revoked_link_is_checked_before_stale(
        client, admin_headers, project, linked_results_repo, global_results_repo, make_task):
    task = pinned_task(project, make_task)
    set_target_dir(client, admin_headers, project, global_results_repo, "out")
    url = f"/projects/{project.id}/repositories/results/{global_results_repo.id}"
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    task.status = "SUCCESS"
    db.session.commit()
    assert post_result(client, admin_headers, project, task, global_results_repo).json["step"] == "REVOKED"


# --------------------------------------------------------------------------- revoked resources


@pytest.fixture
def full_task(client, admin_headers, project, pr_trigger, spec_raw, linked_dataset, linked_results_repo) -> Task:
    """A task made from a pull request, on the project's dataset, with its results link: all three active."""
    created = client.post(f"{pr_trigger}/task", json={"spec_raw": spec_raw}, headers=admin_headers)
    assert created.status_code == 201, created.json
    task = reload_task(created.json["id"])
    assert task.spec.dataset_id is not None and task.config_snapshot["results"] is not None
    return task


@pytest.fixture
def links(project, global_trigger_repo, global_dataset, global_results_repo) -> dict:
    """Per resource of a task: the URL of the project's link to it, and the name revoked gives it."""
    return {
        "trigger": (f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}",
                    f"trigger repository {global_trigger_repo.repo_path}"),
        "dataset": (f"/projects/{project.id}/datasets/{global_dataset.id}", f"dataset {global_dataset.name}"),
        "results": (f"/projects/{project.id}/repositories/results/{global_results_repo.id}",
                    f"results repository {global_results_repo.repo_path}"),
    }


def revoked_of(client, admin_headers, project, task) -> list[str]:
    response = client.get(config_url(project, task), headers=admin_headers)
    assert response.status_code == 200, response.json
    return response.json["revoked"]


def test_nothing_is_revoked_for_a_current_task_or_for_links_only_switched_off(
        client, admin_headers, project, full_task, links):
    assert revoked_of(client, admin_headers, project, full_task) == []
    for url, _ in links.values():
        assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 200
    assert revoked_of(client, admin_headers, project, full_task) == []


@pytest.mark.parametrize("kind", ["trigger", "dataset", "results"])
def test_a_revoked_link_is_named(client, admin_headers, project, full_task, links, kind):
    url, name = links[kind]
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    assert revoked_of(client, admin_headers, project, full_task) == [name]
    # revoking is the controller's and does not touch the other rules: the snapshot is still current
    assert client.get(config_url(project, full_task), headers=admin_headers).json["current"] is True


@pytest.mark.parametrize("kind", ["dataset", "results"])
def test_a_deleted_link_is_named(client, admin_headers, project, full_task, links, kind):
    url, name = links[kind]
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert revoked_of(client, admin_headers, project, full_task) == [name]


def test_every_revoked_link_is_named_in_the_order_of_the_trigger_dataset_and_results(
        client, admin_headers, project, full_task, links):
    for url, _ in links.values():
        assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    assert revoked_of(client, admin_headers, project, full_task) == [name for _, name in links.values()]


def test_a_dataset_the_project_has_no_link_to_is_revoked(
        client, admin_headers, project, global_dataset, make_task):
    task = make_task(dataset_id=global_dataset.id)
    assert revoked_of(client, admin_headers, project, task) == [f"dataset {global_dataset.name}"]


def test_a_task_without_a_pull_request_or_a_snapshot_is_checked_against_the_projects_results_link(
        client, admin_headers, project, linked_results_repo, global_results_repo, make_task):
    task = make_task()
    assert revoked_of(client, admin_headers, project, task) == []
    url = f"/projects/{project.id}/repositories/results/{global_results_repo.id}"
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    assert revoked_of(client, admin_headers, project, task) == [f"results repository {global_results_repo.repo_path}"]


@pytest.fixture
def global_revokes(project, global_trigger_repo, global_dataset, global_results_repo) -> dict:
    """Per kind: the URL PATCHed with {"revoked": true}, and the name a task's revoked list gives it then."""
    provider = global_trigger_repo.provider
    return {
        "project": (f"/projects/{project.id}", f"project {project.name} (revoked)"),
        "trigger": (f"/global/repositories/triggers/{global_trigger_repo.id}",
                    f"trigger repository {global_trigger_repo.repo_path} (revoked)"),
        "dataset": (f"/global/datasets/{global_dataset.id}", f"dataset {global_dataset.name} (revoked)"),
        "results": (f"/global/repositories/results/{global_results_repo.id}",
                    f"results repository {global_results_repo.repo_path} (revoked)"),
        # both repositories are on it: it is named once
        "provider": (f"/global/providers/{provider.id}", f"provider {provider.name} (revoked)"),
    }


@pytest.mark.parametrize("kind", ["project", "trigger", "dataset", "results", "provider"])
def test_a_revoked_global_resource_provider_or_project_is_named_until_it_is_restored(
        client, admin_headers, project, full_task, global_revokes, kind):
    url, name = global_revokes[kind]
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    assert revoked_of(client, admin_headers, project, full_task) == [name]
    # revoking is the controller's and does not touch the other rules: the snapshot is still current
    assert client.get(config_url(project, full_task), headers=admin_headers).json["current"] is True

    assert client.patch(url, json={"revoked": False}, headers=admin_headers).status_code == 200
    assert revoked_of(client, admin_headers, project, full_task) == []


def test_everything_revoked_is_named_once_the_project_first(
        client, admin_headers, project, full_task, links, global_revokes):
    for url, _ in (*links.values(), *global_revokes.values()):
        assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    names = {kind: name for kind, (_, name) in links.items()}
    revoked = {kind: name for kind, (_, name) in global_revokes.items()}
    assert revoked_of(client, admin_headers, project, full_task) == [
        revoked["project"],
        names["trigger"], revoked["trigger"], revoked["provider"],
        names["dataset"], revoked["dataset"],
        names["results"], revoked["results"],
    ]


def test_a_task_without_a_pull_request_names_its_revoked_dataset_and_the_projects_results_repository(
        client, admin_headers, project, linked_dataset, linked_results_repo, global_dataset, global_results_repo,
        make_task):
    task = make_task(dataset_id=global_dataset.id)
    assert revoked_of(client, admin_headers, project, task) == []
    for url in (f"/global/datasets/{global_dataset.id}", f"/global/repositories/results/{global_results_repo.id}"):
        assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    assert revoked_of(client, admin_headers, project, task) == [
        f"dataset {global_dataset.name} (revoked)", f"results repository {global_results_repo.repo_path} (revoked)",
    ]


def test_stale_step_is_a_valid_filter(client, admin_headers, project):
    assert client.get(f"/projects/{project.id}/results?step=STALE", headers=admin_headers).status_code == 200


# --------------------------------------------------------------------------- guards: edits are not refused


def test_edit_of_target_dir_enabled_and_delete_of_an_enabled_project_with_a_task_in_flight(
        client, admin_headers, project, linked_results_repo, global_results_repo, make_task):
    make_task()  # in flight
    url = f"/projects/{project.id}/repositories/results/{global_results_repo.id}"
    assert project.enabled is True
    assert client.patch(url, json={"target_dir": "out"}, headers=admin_headers).status_code == 200
    assert client.put(url, json={"target_dir": "again"}, headers=admin_headers).status_code == 200
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 200
    assert client.put(url, json={"target_dir": "again", "enabled": False}, headers=admin_headers).status_code == 200
    assert client.get(url, headers=admin_headers).json["target_dir"] == "again"
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).status_code == 404


# --------------------------------------------------------------------------- the launch decision


def decision_of(client, admin_headers, project, task) -> tuple[str, str | None]:
    response = client.get(config_url(project, task), headers=admin_headers)
    assert response.status_code == 200, response.json
    return response.json["outcome"], response.json["cause"]


def patch(client, admin_headers, url, **body):
    assert client.patch(url, json=body, headers=admin_headers).status_code == 200


def test_everything_clear_is_launch_with_no_cause(client, admin_headers, project, full_task):
    assert decision_of(client, admin_headers, project, full_task) == ("launch", None)


def test_a_task_without_a_dataset_is_launch(client, admin_headers, project, make_task):
    assert decision_of(client, admin_headers, project, make_task()) == ("launch", None)


def test_a_revoked_resource_fails_with_the_revoked_cause(client, admin_headers, project, full_task, links):
    url, name = links["dataset"]
    patch(client, admin_headers, url, revoked=True)
    assert decision_of(client, admin_headers, project, full_task) == ("fail", f"revoked: {name}")


def test_every_revoked_name_is_in_the_cause(client, admin_headers, project, full_task, links):
    for url, _ in links.values():
        patch(client, admin_headers, url, revoked=True)
    names = [name for _, name in links.values()]
    assert decision_of(client, admin_headers, project, full_task) == ("fail", "revoked: " + "; ".join(names))


def test_revoked_wins_over_changed(client, admin_headers, project, linked_results_repo, global_results_repo, make_task):
    task = pinned_task(project, make_task)
    set_target_dir(client, admin_headers, project, global_results_repo, "out")
    assert decision_of(client, admin_headers, project, task)[1].startswith("task configuration changed")
    patch(client, admin_headers, f"/projects/{project.id}", revoked=True)
    assert decision_of(client, admin_headers, project, task) == ("fail", f"revoked: project {project.name} (revoked)")


def test_changed_wins_over_the_dataset_link_not_active(
        client, admin_headers, project, full_task, links, global_results_repo):
    set_target_dir(client, admin_headers, project, global_results_repo, "out")
    patch(client, admin_headers, links["dataset"][0], enabled=False)
    outcome, cause = decision_of(client, admin_headers, project, full_task)
    assert outcome == "fail"
    assert cause == "task configuration changed since the task was created: results.target_dir: 'results' -> 'out'"


def test_a_dataset_link_switched_off_fails_naming_the_dataset_and_project(
        client, admin_headers, project, full_task, links, global_dataset):
    patch(client, admin_headers, links["dataset"][0], enabled=False)
    assert decision_of(client, admin_headers, project, full_task) == (
        "fail", f"Dataset {global_dataset.name} is not active in project {project.name}")


def test_a_switched_off_global_dataset_fails_as_not_active_not_revoked(
        client, admin_headers, project, full_task, global_dataset):
    patch(client, admin_headers, f"/global/datasets/{global_dataset.id}", enabled=False)
    outcome, cause = decision_of(client, admin_headers, project, full_task)
    assert outcome == "fail"
    assert cause == f"Dataset {global_dataset.name} is not active in project {project.name}"


def test_a_disabled_dataset_secret_fails_naming_the_dataset(
        client, admin_headers, project, full_task, global_dataset):
    global_dataset.secret.enabled = False
    db.session.commit()
    assert decision_of(client, admin_headers, project, full_task) == (
        "fail", f"The secret of dataset {global_dataset.name} is disabled")


def test_the_dataset_link_not_active_wins_over_a_disabled_secret(
        client, admin_headers, project, full_task, links, global_dataset):
    global_dataset.secret.enabled = False
    db.session.commit()
    patch(client, admin_headers, links["dataset"][0], enabled=False)
    assert decision_of(client, admin_headers, project, full_task) == (
        "fail", f"Dataset {global_dataset.name} is not active in project {project.name}")


def test_asking_for_the_decision_changes_nothing(client, admin_headers, project, full_task):
    before = (full_task.status, full_task.state_cause, full_task.attempt)
    for _ in range(2):
        decision_of(client, admin_headers, project, full_task)
    db.session.expire_all()
    task = reload_task(full_task.id)
    assert (task.status, task.state_cause, task.attempt) == before
