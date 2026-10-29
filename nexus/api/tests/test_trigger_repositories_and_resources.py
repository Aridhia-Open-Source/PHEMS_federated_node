"""
Global trigger repositories and the project resource rules (ADR 0006): create/patch/delete
rules, the resource lifecycle gates (disabled project, in-flight tasks, enabled, revoked) per resource kind, and the active filters.

One lifecycle test per resource kind (secret, dataset, trigger, results) is driven through the Ctx helper; rules
that exist only in the trigger routes use the trigger fixtures directly.
"""
from datetime import datetime, timedelta

import pytest

from app.helpers.base_model import db
from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_secret import ProjectSecret
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request_trigger import PullRequestTrigger
from tests.helpers.pull_requests import add_pull_request_trigger

BASE = "/global/repositories/triggers"
KINDS = ["secret", "dataset", "trigger", "results"]


# --------------------------------------------------------------------------- helpers


class Ctx:
    """URLs and bodies of one resource kind."""

    def __init__(self, kind, obj):
        self.kind, self.obj = kind, obj
        key = obj.label if kind == "secret" else obj.id
        tail = {"secret": f"secrets/{key}", "dataset": f"datasets/{key}",
                "trigger": f"repositories/triggers/{key}", "results": f"repositories/results/{key}"}[kind]
        self._tail = tail
        self.list_tail = tail.rsplit("/", 1)[0]
        self.glob = f"/global/{tail}"
        self.put_body = {"trigger": {"watch_dir": "triggers"}, "results": {"target_dir": "results"}}.get(kind, {})

    def resource(self, pid):
        return f"/projects/{pid}/{self._tail}"


@pytest.fixture
def ctx(request, k8s_client):
    name = {"secret": "global_secret", "dataset": "global_dataset",
            "trigger": "global_trigger_repo", "results": "global_results_repo"}[request.param]
    return Ctx(request.param, request.getfixturevalue(name))


by_kind = pytest.mark.parametrize("ctx", KINDS, indirect=True)


def set_enabled(project, enabled=True):
    project.enabled = enabled
    db.session.commit()


def finish(task, status="FAILED"):
    task.status = status
    db.session.commit()


def assign_to_project(client, admin_headers, c, project):
    """First PUT of the kind into the project (201); the results repository needs a disabled project for it."""
    was_enabled = project.enabled
    if c.kind == "results":
        set_enabled(project, False)
    r = client.put(c.resource(project.id), json=c.put_body, headers=admin_headers)
    assert r.status_code == 201, r.json()
    set_enabled(project, was_enabled)


def _resource_model(c):
    return {"secret": ProjectSecret, "dataset": ProjectDataset, "trigger": ProjectTriggerRepository,
            "results": ProjectResultsRepository}[c.kind]


def patch(client, admin_headers, url, body):
    return client.patch(url, json=body, headers=admin_headers)


def get(client, admin_headers, url):
    return client.get(url, headers=admin_headers)


# --------------------------------------------------------------------------- global trigger repositories


def test_create_get_and_404(client, admin_headers, global_secret, git_provider):
    body = {"provider_id": git_provider.id, "repo_path": "org/new", "secret_label": "test-creds"}
    created = client.post(BASE, json=body, headers=admin_headers)
    assert created.status_code == 201
    assert created.json()["provider"]["api_uri"] == "https://api.github.com"
    assert created.json()["enabled"] is True
    assert created.json()["secret"]["label"] == "test-creds"

    assert get(client, admin_headers, f"{BASE}/{created.json()['id']}").json()["uri"] == "https://github.com/org/new"
    assert get(client, admin_headers, f"{BASE}/999").status_code == 404

    # the same repository under another spelling of the path is a duplicate
    again = client.post(BASE, json={**body, "repo_path": "Org/New.git"}, headers=admin_headers)
    assert again.status_code == 409


@pytest.mark.parametrize("changes", [
    {"secret_label": "nope"},      # unknown secret
    {"provider_id": 999999},       # unknown provider
    {"watch_dir": "x"},            # watch_dir belongs to the project resource, not the global repository
])
def test_create_validation_failures_are_400(client, admin_headers, global_secret, git_provider, changes):
    body = {"provider_id": git_provider.id, "repo_path": "org/new", "secret_label": "test-creds", **changes}
    assert client.post(BASE, json=body, headers=admin_headers).status_code == 400


def test_edit_enabled_and_delete_with_a_task_in_flight(client, admin_headers, assigned_trigger_repo, project, make_task):
    T = assigned_trigger_repo["trigger_repository"]["id"]
    make_task()  # in flight
    disabled = patch(client, admin_headers, f"{BASE}/{T}", {"enabled": False})
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    assert patch(client, admin_headers, f"{BASE}/{T}", {"provider_id": assigned_trigger_repo["trigger_repository"]["provider"]["id"]}).status_code == 200
    assert patch(client, admin_headers, f"{BASE}/{T}", {"secret_label": "test-creds"}).status_code == 200
    assert client.delete(f"{BASE}/{T}", json={}, headers=admin_headers).status_code == 409  # assigned: needs force
    assert client.delete(f"{BASE}/{T}?force=true", json={}, headers=admin_headers).status_code == 204
    assert get(client, admin_headers, f"{BASE}/{T}").status_code == 404


def test_pollable_filter_follows_the_repository_provider_and_secret_only(
        client, admin_headers, project, global_trigger_repo, make_trigger_repo):
    """Listed with: enabled repo + enabled provider + enabled secret. Project resources do not matter."""
    T = global_trigger_repo.id
    ids = lambda q="": [r["id"] for r in get(client, admin_headers, f"{BASE}{q}").json()]  # noqa: E731
    unassigned = make_trigger_repo(uri="github.com/org/unassigned")

    assert ids("?pollable=true") == [T, unassigned.id]  # no project resource and a disabled project are fine
    resource = f"/projects/{project.id}/repositories/triggers/{T}"
    assert client.put(resource, json={"watch_dir": "t"}, headers=admin_headers).status_code == 201
    assert patch(client, admin_headers, resource, {"revoked": True}).status_code == 200
    assert ids("?pollable=true") == [T, unassigned.id]  # a revoked resource does not stop the poll
    global_trigger_repo.enabled = False
    db.session.commit()
    assert ids("?pollable=true") == [unassigned.id]
    unassigned.provider.enabled = False
    db.session.commit()
    assert ids("?pollable=true") == []
    unassigned.provider.enabled = True
    unassigned.secret.enabled = False
    db.session.commit()
    assert ids("?pollable=true") == []


# --------------------------------------------------------------------------- trigger resources


def test_assign_201_lists_and_active_filter(client, admin_headers, project, global_trigger_repo, make_trigger_repo):
    base = f"/projects/{project.id}/repositories/triggers"
    other = make_trigger_repo(uri="github.com/org/triggers2")
    put = client.put(f"{base}/{global_trigger_repo.id}", json={"watch_dir": "triggers", "base_branch": "release"},
                     headers=admin_headers)
    assert put.status_code == 201
    assert (put.json()["watch_dir"], put.json()["base_branch"], put.json()["active"]) == ("triggers", "release", True)
    assert client.put(f"{base}/{other.id}", json={"watch_dir": "t"}, headers=admin_headers).status_code == 201

    # revoked and disabled resources stay listed, but drop out of ?active=true
    assert patch(client, admin_headers, f"{base}/{other.id}", {"revoked": True}).status_code == 200
    assert len(get(client, admin_headers, base).json()) == 2
    active = get(client, admin_headers, f"{base}?active=true")
    assert [x["trigger_repository"]["id"] for x in active.json()] == [global_trigger_repo.id]
    assert patch(client, admin_headers, f"{base}/{global_trigger_repo.id}", {"enabled": False}).status_code == 200
    assert get(client, admin_headers, f"{base}?active=true").json() == []


@pytest.mark.parametrize("repo, project_id, body, status", [
    ("ok", "ok", {}, 400),                          # a resource needs watch_dir
    ("ok", "ok", {"watch_dir": "x", "bogus": 1}, 400),
    (999, "ok", {"watch_dir": "x"}, 404),
    ("ok", 999, {"watch_dir": "x"}, 404),
])
def test_resource_put_errors(client, admin_headers, project, global_trigger_repo, repo, project_id, body, status):
    repo = global_trigger_repo.id if repo == "ok" else repo
    project_id = project.id if project_id == "ok" else project_id
    r = client.put(f"/projects/{project_id}/repositories/triggers/{repo}", json=body, headers=admin_headers)
    assert r.status_code == status


def test_resource_is_invisible_to_other_projects(client, admin_headers, assigned_trigger_repo, other_project):
    repo_id = assigned_trigger_repo["trigger_repository"]["id"]
    assert get(client, admin_headers, f"/projects/{other_project.id}/repositories/triggers/{repo_id}").status_code == 404


def test_revoke_is_admin_only(client, admin_headers, post_json_user_header, assigned_trigger_repo):
    url = f"/projects/{assigned_trigger_repo['project_id']}/repositories/triggers/{assigned_trigger_repo['trigger_repository']['id']}"
    assert patch(client, post_json_user_header, url, {"revoked": True}).status_code == 403
    revoked = patch(client, admin_headers, url, {"revoked": True})
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True and revoked.json()["active"] is False


def test_reassign_put_changes_settings_and_disables(client, admin_headers, assigned_trigger_repo, project):
    url = f"/projects/{assigned_trigger_repo['project_id']}/repositories/triggers/{assigned_trigger_repo['trigger_repository']['id']}"
    assert client.put(url, json={"watch_dir": "another"}, headers=admin_headers).status_code == 200
    r = client.put(url, json={"watch_dir": "other", "enabled": False}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["watch_dir"] == "other" and r.json()["enabled"] is False and r.json()["active"] is False


# --------------------------------------------------------------------------- lifecycle per resource kind


@by_kind
def test_resource_lifecycle_needs_no_drain(ctx, client, admin_headers, project, make_task):
    """Only creating the results resource needs a disabled project; reassign, PATCH enabled and DELETE need no drain."""
    url = ctx.resource(project.id)
    if ctx.kind == "results":
        assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 409
    task = make_task()  # in flight for the rest of the test
    assign_to_project(client, admin_headers, ctx, project)
    resource = get(client, admin_headers, url).json()
    assert resource["active"] is True and resource["enabled"] is True and resource["revoked"] is False

    assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 200
    r = client.put(url, json={**ctx.put_body, "enabled": False}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["active"] is False
    assert patch(client, admin_headers, url, {"enabled": True}).json()["active"] is True
    assert patch(client, admin_headers, url, {"enabled": False}).json()["active"] is False
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert task.status == "PENDING"
    assert get(client, admin_headers, url).status_code == 404
    assert get(client, admin_headers, f"/projects/{project.id}/{ctx.list_tail}").json() == []
    assert get(client, admin_headers, ctx.glob).status_code == 200  # the global resource survives an unassign


@by_kind
def test_unassigning_revokes_the_resource_and_it_can_be_assigned_again(ctx, client, admin_headers, project):
    assign_to_project(client, admin_headers, ctx, project)
    url = ctx.resource(project.id)
    assert client.delete(url, headers=admin_headers).status_code == 204
    (row,) = db.session.query(_resource_model(ctx)).execution_options(include_deleted=True).filter_by(
        project_id=project.id
    ).all()
    assert row.deleted_at is not None and row.revoked is True
    assign_to_project(client, admin_headers, ctx, project)  # a new, live resource of the same pair
    assert get(client, admin_headers, url).json()["revoked"] is False
    assert len(get(client, admin_headers, f"/projects/{project.id}/{ctx.list_tail}").json()) == 1


def test_unassigning_a_trigger_resource_with_pull_requests_keeps_its_triggers(
    client, admin_headers, project, assigned_trigger_repo
):
    """The unassign is a soft delete, so the RESTRICT keys of the triggers never fire: 204, not an error."""
    url = f"/projects/{project.id}/repositories/triggers/{assigned_trigger_repo['trigger_repository']['id']}"
    add_pull_request_trigger(ProjectTriggerRepository.query.one())
    assert client.delete(url, headers=admin_headers).status_code == 204
    (row,) = db.session.query(ProjectTriggerRepository).execution_options(include_deleted=True).all()
    assert row.deleted_at is not None and row.revoked is True
    assert PullRequestTrigger.query.filter_by(project_trigger_repository_id=row.id).count() == 1
    assert get(client, admin_headers, url).status_code == 404


@by_kind
def test_revoke_and_unrevoke_semantics(ctx, client, admin_headers, project, make_task):
    assign_to_project(client, admin_headers, ctx, project)
    url = ctx.resource(project.id)

    # the row stays visible and listed, but inactive
    r = patch(client, admin_headers, url, {"revoked": True})
    assert r.status_code == 200
    assert r.json()["revoked"] is True and r.json()["active"] is False and r.json()["enabled"] is True
    assert get(client, admin_headers, url).json()["active"] is False
    listed = get(client, admin_headers, f"/projects/{project.id}/{ctx.list_tail}").json()
    assert len(listed) == 1 and listed[0]["active"] is False

    # re-grant and revoke stay immediate with a task in flight
    task = make_task()
    assert patch(client, admin_headers, url, {"revoked": False}).json()["active"] is True
    assert patch(client, admin_headers, url, {"revoked": True}).json()["active"] is False

    # revoke only touches `revoked`: a resource disabled earlier stays disabled after the re-grant
    finish(task)
    patch(client, admin_headers, url, {"revoked": False})
    assert patch(client, admin_headers, url, {"enabled": False}).status_code == 200
    assert patch(client, admin_headers, url, {"revoked": True}).json()["enabled"] is False
    regranted = patch(client, admin_headers, url, {"revoked": False}).json()
    assert regranted["enabled"] is False and regranted["active"] is False
    assert patch(client, admin_headers, url, {"enabled": True}).json()["active"] is True


@pytest.mark.parametrize("kind, body, field, value", [
    ("trigger", {"watch_dir": "other"}, "watch_dir", "other"),
    ("results", {"target_dir": "out"}, "target_dir", "out"),
])
def test_resource_settings_patch_with_a_task_in_flight(kind, body, field, value, client, admin_headers, project,
                                                        global_trigger_repo, global_results_repo, make_task):
    c = Ctx(kind, global_trigger_repo if kind == "trigger" else global_results_repo)
    assign_to_project(client, admin_headers, c, project)
    url = c.resource(project.id)
    # with a task in flight: the tasks are pinned to the old setting instead
    make_task()
    r = patch(client, admin_headers, url, body)
    assert r.status_code == 200 and r.json()[field] == value
    assert patch(client, admin_headers, url, {**body, "enabled": False}).status_code == 200


def test_dataset_resource_has_no_settings(client, admin_headers, project, global_dataset):
    c = Ctx("dataset", global_dataset)
    assign_to_project(client, admin_headers, c, project)
    assert patch(client, admin_headers, c.resource(project.id), {"host": "x"}).status_code == 400
    assert patch(client, admin_headers, c.resource(project.id), {}).status_code == 400


@by_kind
def test_global_patch_and_delete_with_a_task_in_flight(ctx, client, admin_headers, project, other_project,
                                                           make_task):
    """A globally disabled resource makes its project resources inactive; deleting it revokes and deletes every one."""
    gdisable = lambda on: patch(client, admin_headers, ctx.glob, {"enabled": on})  # noqa: E731
    assign_to_project(client, admin_headers, ctx, project)
    assign_to_project(client, admin_headers, ctx, other_project)
    make_task(project=other_project)  # in flight
    r = gdisable(False)
    assert r.status_code in (200, 202) and r.json()["enabled"] is False
    for p in (project, other_project):
        resource = get(client, admin_headers, ctx.resource(p.id)).json()
        assert resource["active"] is False and resource["enabled"] is True and resource["revoked"] is False
    assert gdisable(True).status_code in (200, 202)
    assert get(client, admin_headers, ctx.resource(project.id)).json()["active"] is True

    if ctx.kind != "secret":  # a secret still goes with its project resources, the others need force while projects are assigned
        refused = client.delete(ctx.glob, headers=admin_headers)
        assert refused.status_code == 409
        assert sorted(p["id"] for p in refused.json()["details"]) == [project.id, other_project.id]
        assert {p["name"] for p in refused.json()["details"]} == {project.name, other_project.name}
        assert get(client, admin_headers, ctx.glob).status_code == 200
    assert client.delete(f"{ctx.glob}?force=true", headers=admin_headers).status_code == 204
    assert get(client, admin_headers, ctx.glob).status_code == 404
    for p in (project, other_project):
        assert get(client, admin_headers, ctx.resource(p.id)).status_code == 404
        assert get(client, admin_headers, f"/projects/{p.id}/{ctx.list_tail}").json() == []
    resources = db.session.query(_resource_model(ctx)).execution_options(include_deleted=True).all()
    assert len(resources) == 2 and all(resource.deleted_at is not None and resource.revoked for resource in resources)


def test_global_delete_without_project_resources_needs_no_force(client, admin_headers, global_dataset, project):
    c = Ctx("dataset", global_dataset)
    assign_to_project(client, admin_headers, c, project)
    assert client.delete(c.resource(project.id), headers=admin_headers).status_code == 204  # unassigned: no live resource left
    assert client.delete(c.glob, headers=admin_headers).status_code == 204


def test_global_delete_without_project_resources(client, admin_headers, global_dataset):
    assert client.delete(f"/global/datasets/{global_dataset.id}", headers=admin_headers).status_code == 204


def test_secret_rotation_and_enabled_apply_at_once(client, admin_headers, k8s_client, project, other_project,
                                                  global_secret):
    c = Ctx("secret", global_secret)
    assign_to_project(client, admin_headers, c, project)
    assign_to_project(client, admin_headers, c, other_project)
    assert patch(client, admin_headers, c.glob, {"values": {"TOKEN": "t2"}}).status_code == 200
    assert patch(client, admin_headers, c.glob, {"enabled": False}).status_code == 200


@by_kind
def test_a_deleted_global_resource_is_gone_and_its_name_is_free_again(ctx, client, admin_headers, k8s_client):
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 204
    assert get(client, admin_headers, ctx.glob).status_code == 404
    listing = get(client, admin_headers, ctx.glob.rsplit("/", 1)[0]).json()
    assert (listing["items"] if isinstance(listing, dict) else listing) == []
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 404
    assert type(ctx.obj).query.execution_options(include_deleted=True).count() == 1  # kept for audit
    assert type(ctx.obj).query.count() == 0


def test_two_projects_assign_one_repo_independently(client, admin_headers, project, other_project, global_trigger_repo):
    """Revoking or disabling in one project never leaks into the other."""
    c = Ctx("trigger", global_trigger_repo)
    assign_to_project(client, admin_headers, c, project)
    assign_to_project(client, admin_headers, c, other_project)
    assert patch(client, admin_headers, c.resource(project.id), {"revoked": True}).status_code == 200
    assert patch(client, admin_headers, c.resource(other_project.id), {"enabled": False}).status_code == 200
    assert get(client, admin_headers, c.resource(project.id)).json()["enabled"] is True
    other = get(client, admin_headers, c.resource(other_project.id)).json()
    assert other["revoked"] is False and other["active"] is False


@pytest.mark.parametrize("off, on", [
    ({"enabled": False}, {"enabled": True}),
    ({"revoked": True}, {"revoked": False}),
])
def test_switching_a_repository_back_on_skips_the_gap(client, admin_headers, system_headers, project, global_trigger_repo, off, on):
    """Pull requests merged before the repository was switched back on (or restored) are stored but get no trigger; later ones do."""
    T = global_trigger_repo.id
    resource = f"/projects/{project.id}/repositories/triggers/{T}"
    assert client.put(resource, json={"watch_dir": "triggers"}, headers=admin_headers).status_code == 201
    # Start the resource's cursor far back, so the first pull request is in its scope but for the re-enable
    assignment = ProjectTriggerRepository.query.filter_by(project_id=project.id, trigger_repository_id=T).one()
    assignment.initial_cursor = datetime(2000, 1, 1)
    db.session.commit()

    def pull_request(number, merged_at):
        return {
            "number": number, "title": f"PR {number}", "raised_by": "user1",
            "merged_at": merged_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "merge_commit_sha": f"{number:040x}",
            "base_branch": "main", "files_truncated": False,
            "changed_files": [{"path": "triggers/spec.json", "status": "added"}],
        }

    assert patch(client, admin_headers, f"{BASE}/{T}", off).status_code == 200
    assert patch(client, admin_headers, f"{BASE}/{T}", on).status_code == 200

    merged_before = datetime.utcnow() - timedelta(hours=1)
    merged_after = datetime.utcnow() + timedelta(days=1)
    r = client.post(f"{BASE}/{T}/pull_requests", headers=system_headers, json={
        "pull_requests": [pull_request(1, merged_before), pull_request(2, merged_after)]
    })
    assert r.status_code == 201, r.json()
    assert r.json()["created"] == [1, 2]

    stored = get(client, admin_headers, f"{BASE}/{T}/pull_requests?per_page=50").json()
    assert sorted(i["number"] for i in stored["items"]) == [1, 2]
    triggers = get(client, admin_headers, f"{resource}/pull_requests?per_page=50").json()
    assert [i["number"] for i in triggers["items"]] == [2]


# --------------------------------------------------------------------------- global revoke (PATCH revoked)

# The kinds that are revoked with PATCH {"revoked": true}; the secret (parked) cannot be revoked
by_global = pytest.mark.parametrize("ctx", ["dataset", "trigger", "results"], indirect=True)


@by_global
@pytest.mark.parametrize("value", ["yes", 1, None])
def test_patch_revoked_must_be_a_boolean(ctx, client, admin_headers, value):
    assert patch(client, admin_headers, ctx.glob, {"revoked": value}).status_code == 400
    assert get(client, admin_headers, ctx.glob).json()["revoked"] is False


@by_global
def test_patch_revoked_is_admin_only_shows_in_the_dto_and_leaves_enabled_alone(
        ctx, client, admin_headers, post_json_user_header):
    assert get(client, admin_headers, ctx.glob).json()["revoked"] is False
    assert patch(client, post_json_user_header, ctx.glob, {"revoked": True}).status_code == 403
    assert get(client, admin_headers, ctx.glob).json()["revoked"] is False

    revoked = patch(client, admin_headers, ctx.glob, {"revoked": True})
    assert revoked.status_code == 200, revoked.json()
    assert (revoked.json()["revoked"], revoked.json()["enabled"]) == (True, True)
    assert get(client, admin_headers, ctx.glob).json()["revoked"] is True

    # one call restores it, and clears the flag only
    restored = patch(client, admin_headers, ctx.glob, {"revoked": False})
    assert (restored.json()["revoked"], restored.json()["enabled"]) == (False, True)


@by_global
def test_a_revoked_global_resource_makes_its_project_resources_inactive_one_created_later_too(
        ctx, client, admin_headers, project, other_project):
    assign_to_project(client, admin_headers, ctx, project)
    assert get(client, admin_headers, ctx.resource(project.id)).json()["active"] is True

    assert patch(client, admin_headers, ctx.glob, {"revoked": True}).status_code == 200
    # the resource is untouched: the global resource is what says no
    resource = get(client, admin_headers, ctx.resource(project.id)).json()
    assert (resource["enabled"], resource["revoked"], resource["active"]) == (True, False, False)
    assign_to_project(client, admin_headers, ctx, other_project)
    later = get(client, admin_headers, ctx.resource(other_project.id)).json()
    assert (later["enabled"], later["revoked"], later["active"]) == (True, False, False)

    assert patch(client, admin_headers, ctx.glob, {"revoked": False}).status_code == 200
    assert get(client, admin_headers, ctx.resource(project.id)).json()["active"] is True
    assert get(client, admin_headers, ctx.resource(other_project.id)).json()["active"] is True


def test_a_revoked_trigger_repository_is_not_polled_and_takes_no_pull_requests(
        client, admin_headers, system_headers, project, global_trigger_repo, make_trigger_repo, make_pr_batch):
    T = global_trigger_repo.id
    ids = lambda q="": [r["id"] for r in get(client, admin_headers, f"{BASE}{q}").json()]  # noqa: E731
    unassigned = make_trigger_repo(uri="github.com/org/unassigned")
    assert ids("?pollable=true") == [T, unassigned.id]

    assert patch(client, admin_headers, f"{BASE}/{T}", {"revoked": True}).status_code == 200
    assert ids("?pollable=true") == [unassigned.id]
    assert ids() == [T, unassigned.id]  # still listed
    refused = client.post(f"{BASE}/{T}/pull_requests", json=make_pr_batch(1), headers=system_headers)
    assert refused.status_code == 400 and "revoked" in refused.json()["error"]
    assert get(client, admin_headers, f"{BASE}/{T}/pull_requests").json()["total"] == 0  # nothing stored

    assert patch(client, admin_headers, f"{BASE}/{T}", {"revoked": False}).status_code == 200
    assert ids("?pollable=true") == [T, unassigned.id]
    assert client.post(f"{BASE}/{T}/pull_requests", json=make_pr_batch(1), headers=system_headers).status_code == 201
