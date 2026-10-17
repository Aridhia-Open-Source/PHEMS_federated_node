"""
Global trigger repositories and the project link rules (ADR 0019 sections 2, 9 and 11): create/patch/delete
rules, the link lifecycle gates (lock, in-flight tasks, enabled, revoked) per link kind, and the active filters.

One lifecycle test per link kind (secret, dataset, trigger, results) is driven through the Ctx helper; rules
that exist only in the trigger routes use the trigger fixtures directly.
"""
from datetime import datetime, timedelta

import pytest

from app.helpers.base_model import db
from app.models.project_trigger_repository import ProjectTriggerRepository

BASE = "/global/repositories/triggers"
KINDS = ["secret", "dataset", "trigger", "results"]


# --------------------------------------------------------------------------- helpers


class Ctx:
    """URLs and bodies of one link kind."""

    def __init__(self, kind, obj):
        self.kind, self.obj = kind, obj
        key = obj.label if kind == "secret" else obj.id
        tail = {"secret": f"secrets/{key}", "dataset": f"datasets/{key}",
                "trigger": f"repositories/triggers/{key}", "results": f"repositories/results/{key}"}[kind]
        self._tail = tail
        self.list_tail = tail.rsplit("/", 1)[0]
        self.glob = f"/global/{tail}"
        self.put_body = {"trigger": {"watch_dir": "triggers"}, "results": {"target_dir": "results"}}.get(kind, {})

    def link(self, pid):
        return f"/projects/{pid}/{self._tail}"


@pytest.fixture
def ctx(request, k8s_client):
    name = {"secret": "global_secret", "dataset": "global_dataset",
            "trigger": "global_trigger_repo", "results": "global_results_repo"}[request.param]
    return Ctx(request.param, request.getfixturevalue(name))


by_kind = pytest.mark.parametrize("ctx", KINDS, indirect=True)


def set_locked(project, locked=True):
    project.locked = locked
    db.session.commit()


def finish(task, status="FAILED"):
    task.status = status
    db.session.commit()


def link_project(client, admin_headers, c, project):
    """First PUT of the kind into the project (201); the results repository needs a locked project for it."""
    was_locked = project.locked
    if c.kind == "results":
        set_locked(project)
    r = client.put(c.link(project.id), json=c.put_body, headers=admin_headers)
    assert r.status_code == 201, r.json
    set_locked(project, was_locked)


def patch(client, admin_headers, url, body):
    return client.patch(url, json=body, headers=admin_headers)


def get(client, admin_headers, url):
    return client.get(url, headers=admin_headers)


# --------------------------------------------------------------------------- global trigger repositories


def test_create_get_and_404(client, admin_headers, global_secret, git_provider):
    body = {"provider_id": git_provider.id, "repo_path": "org/new", "secret_label": "test-creds"}
    created = client.post(BASE, json=body, headers=admin_headers)
    assert created.status_code == 201
    assert created.json["provider"]["api_uri"] == "https://api.github.com"
    assert created.json["enabled"] is True
    assert created.json["secret"]["label"] == "test-creds"

    assert get(client, admin_headers, f"{BASE}/{created.json['id']}").json["uri"] == "https://github.com/org/new"
    assert get(client, admin_headers, f"{BASE}/999").status_code == 404

    # the same repository under another spelling of the path is a duplicate
    again = client.post(BASE, json={**body, "repo_path": "Org/New.git"}, headers=admin_headers)
    assert again.status_code == 409


@pytest.mark.parametrize("changes", [
    {"secret_label": "nope"},      # unknown secret
    {"provider_id": 999999},       # unknown provider
    {"watch_dir": "x"},            # watch_dir belongs to the project link, not the global repository
])
def test_create_validation_failures_are_400(client, admin_headers, global_secret, git_provider, changes):
    body = {"provider_id": git_provider.id, "repo_path": "org/new", "secret_label": "test-creds", **changes}
    assert client.post(BASE, json=body, headers=admin_headers).status_code == 400


def test_patch_and_delete_need_a_drained_lock_except_secret_swap(client, admin_headers, linked_trigger_repo, project):
    T = linked_trigger_repo["trigger_repository"]["id"]
    assert patch(client, admin_headers, f"{BASE}/{T}", {"enabled": False}).status_code == 409
    assert patch(client, admin_headers, f"{BASE}/{T}", {"provider_id": linked_trigger_repo["trigger_repository"]["provider"]["id"]}).status_code == 409
    # swapping the secret is exempt from the lock
    assert patch(client, admin_headers, f"{BASE}/{T}", {"secret_label": "test-creds"}).status_code == 200

    set_locked(project)
    disabled = patch(client, admin_headers, f"{BASE}/{T}", {"enabled": False})
    assert disabled.status_code == 200 and disabled.json["enabled"] is False
    assert client.delete(f"{BASE}/{T}", json={}, headers=admin_headers).status_code == 204
    assert get(client, admin_headers, f"{BASE}/{T}").status_code == 404


def test_active_link_filter_follows_every_flag(client, admin_headers, project, global_trigger_repo,
                                               make_trigger_repo):
    """Listed only with: enabled project + enabled link + not revoked + enabled global repo."""
    T = global_trigger_repo.id
    unlinked = make_trigger_repo(uri="github.com/org/unlinked")
    link = f"/projects/{project.id}/repositories/triggers/{T}"
    assert client.put(link, json={"watch_dir": "t"}, headers=admin_headers).status_code == 201
    ids = lambda q="": [r["id"] for r in get(client, admin_headers, f"{BASE}{q}").json]  # noqa: E731

    assert ids() == [T, unlinked.id]
    assert ids("?active_link=true") == []  # the project is still disabled
    assert patch(client, admin_headers, f"/projects/{project.id}", {"locked": True}).status_code == 200
    assert patch(client, admin_headers, f"/projects/{project.id}", {"enabled": True}).status_code == 200
    assert ids("?active_link=true") == [T]
    for off, on in (({"revoked": True}, {"revoked": False}), ({"enabled": False}, {"enabled": True})):
        patch(client, admin_headers, link, off)
        assert ids("?active_link=true") == []
        patch(client, admin_headers, link, on)
        assert ids("?active_link=true") == [T]
    assert patch(client, admin_headers, f"{BASE}/{T}", {"enabled": False}).status_code == 200
    assert ids("?active_link=true") == []


# --------------------------------------------------------------------------- trigger links


def test_link_201_lists_and_active_filter(client, admin_headers, project, global_trigger_repo, make_trigger_repo):
    base = f"/projects/{project.id}/repositories/triggers"
    other = make_trigger_repo(uri="github.com/org/triggers2")
    put = client.put(f"{base}/{global_trigger_repo.id}", json={"watch_dir": "triggers", "base_branch": "release"},
                     headers=admin_headers)
    assert put.status_code == 201
    assert (put.json["watch_dir"], put.json["base_branch"], put.json["active"]) == ("triggers", "release", True)
    assert client.put(f"{base}/{other.id}", json={"watch_dir": "t"}, headers=admin_headers).status_code == 201

    # revoked and disabled links stay listed, but drop out of ?active=true
    assert patch(client, admin_headers, f"{base}/{other.id}", {"revoked": True}).status_code == 200
    assert len(get(client, admin_headers, base).json) == 2
    active = get(client, admin_headers, f"{base}?active=true")
    assert [x["trigger_repository"]["id"] for x in active.json] == [global_trigger_repo.id]
    set_locked(project)
    assert patch(client, admin_headers, f"{base}/{global_trigger_repo.id}", {"enabled": False}).status_code == 200
    assert get(client, admin_headers, f"{base}?active=true").json == []


@pytest.mark.parametrize("repo, project_id, body, status", [
    ("ok", "ok", {}, 400),                          # a link needs watch_dir
    ("ok", "ok", {"watch_dir": "x", "bogus": 1}, 400),
    (999, "ok", {"watch_dir": "x"}, 404),
    ("ok", 999, {"watch_dir": "x"}, 404),
])
def test_link_put_errors(client, admin_headers, project, global_trigger_repo, repo, project_id, body, status):
    repo = global_trigger_repo.id if repo == "ok" else repo
    project_id = project.id if project_id == "ok" else project_id
    r = client.put(f"/projects/{project_id}/repositories/triggers/{repo}", json=body, headers=admin_headers)
    assert r.status_code == status


def test_link_is_invisible_to_other_projects(client, admin_headers, linked_trigger_repo, other_project):
    repo_id = linked_trigger_repo["trigger_repository"]["id"]
    assert get(client, admin_headers, f"/projects/{other_project.id}/repositories/triggers/{repo_id}").status_code == 404


def test_revoke_is_admin_only(client, admin_headers, post_json_user_header, linked_trigger_repo):
    url = f"/projects/{linked_trigger_repo['project_id']}/repositories/triggers/{linked_trigger_repo['trigger_repository']['id']}"
    assert patch(client, post_json_user_header, url, {"revoked": True}).status_code == 403
    revoked = patch(client, admin_headers, url, {"revoked": True})
    assert revoked.status_code == 200
    assert revoked.json["revoked"] is True and revoked.json["active"] is False


def test_relink_put_can_disable_link_and_needs_lock(client, admin_headers, linked_trigger_repo, project):
    url = f"/projects/{linked_trigger_repo['project_id']}/repositories/triggers/{linked_trigger_repo['trigger_repository']['id']}"
    assert client.put(url, json={"watch_dir": "other"}, headers=admin_headers).status_code == 409
    set_locked(project)
    r = client.put(url, json={"watch_dir": "other", "enabled": False}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json["watch_dir"] == "other" and r.json["enabled"] is False and r.json["active"] is False


# --------------------------------------------------------------------------- lifecycle per link kind


@by_kind
def test_link_lifecycle_gates(ctx, client, admin_headers, project, make_task):
    """First link, relink, PATCH enabled and DELETE: each is gated by the lock and by tasks in flight."""
    url = ctx.link(project.id)
    # first link: only the results repository needs a drained, locked project
    if ctx.kind == "results":
        assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 409
        set_locked(project)
        task = make_task()
        assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 409
        finish(task)
        set_locked(project, False)
    else:
        task = make_task()  # a task in flight does not block a new watcher / grant
    link_project(client, admin_headers, ctx, project)
    finish(task, "PENDING")
    linked = get(client, admin_headers, url).json
    assert linked["active"] is True and linked["enabled"] is True and linked["revoked"] is False

    # unlocked project: every change is refused
    assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 409
    assert patch(client, admin_headers, url, {"enabled": False}).status_code == 409
    assert client.delete(url, headers=admin_headers).status_code == 409

    # locked with a task in flight: still refused, and the response names the task
    set_locked(project)
    r = client.put(url, json=ctx.put_body, headers=admin_headers)
    assert r.status_code == 409 and r.json["details"] == [task.id]
    assert patch(client, admin_headers, url, {"enabled": False}).status_code == 409
    assert client.delete(url, headers=admin_headers).status_code == 409
    assert get(client, admin_headers, url).status_code == 200

    # drained: relink (200), disable/enable and unlink succeed; the global resource survives an unlink
    finish(task)
    assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 200
    off = patch(client, admin_headers, url, {"enabled": False})
    assert off.status_code == 200 and off.json["enabled"] is False and off.json["active"] is False
    assert patch(client, admin_headers, url, {"enabled": True}).json["active"] is True
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert get(client, admin_headers, url).status_code == 404
    assert get(client, admin_headers, ctx.glob).status_code == 200


@pytest.mark.parametrize("status, expected", [
    ("SUCCESS", 409),  # succeeded with no result delivered yet still needs the link (ADR section 9)
    ("CANCELED", 204),
])
def test_dataset_unlink_by_task_status(client, admin_headers, project, global_dataset, make_task, status, expected):
    url = f"/projects/{project.id}/datasets/{global_dataset.id}"
    assert client.put(url, json={}, headers=admin_headers).status_code == 201
    set_locked(project)
    make_task(status=status)
    assert client.delete(url, headers=admin_headers).status_code == expected


@by_kind
def test_revoke_and_unrevoke_semantics(ctx, client, admin_headers, project, make_task):
    link_project(client, admin_headers, ctx, project)
    url = ctx.link(project.id)

    # revoke together with enabled is still gated by the lock, and applies nothing
    assert patch(client, admin_headers, url, {"revoked": True, "enabled": False}).status_code == 409
    assert get(client, admin_headers, url).json["revoked"] is False

    # revoke needs no lock; the row stays visible and listed, but inactive
    r = patch(client, admin_headers, url, {"revoked": True})
    assert r.status_code == 200
    assert r.json["revoked"] is True and r.json["active"] is False and r.json["enabled"] is True
    assert get(client, admin_headers, url).json["active"] is False
    listed = get(client, admin_headers, f"/projects/{project.id}/{ctx.list_tail}").json
    assert len(listed) == 1 and listed[0]["active"] is False

    # re-grant and revoke stay immediate with the project locked and a task in flight
    set_locked(project)
    task = make_task()
    assert patch(client, admin_headers, url, {"revoked": False}).json["active"] is True
    assert patch(client, admin_headers, url, {"revoked": True}).json["active"] is False

    # revoke only touches `revoked`: a link disabled earlier stays disabled after the re-grant
    finish(task)
    patch(client, admin_headers, url, {"revoked": False})
    assert patch(client, admin_headers, url, {"enabled": False}).status_code == 200
    assert patch(client, admin_headers, url, {"revoked": True}).json["enabled"] is False
    regranted = patch(client, admin_headers, url, {"revoked": False}).json
    assert regranted["enabled"] is False and regranted["active"] is False
    assert patch(client, admin_headers, url, {"enabled": True}).json["active"] is True


@pytest.mark.parametrize("kind, body, field, value", [
    ("trigger", {"watch_dir": "other"}, "watch_dir", "other"),
    ("results", {"target_dir": "out"}, "target_dir", "out"),
])
def test_link_settings_patch_needs_lock_and_drained_project(kind, body, field, value, client, admin_headers, project,
                                                            global_trigger_repo, global_results_repo, make_task):
    c = Ctx(kind, global_trigger_repo if kind == "trigger" else global_results_repo)
    link_project(client, admin_headers, c, project)
    url = c.link(project.id)
    assert patch(client, admin_headers, url, body).status_code == 409
    set_locked(project)
    task = make_task()
    assert patch(client, admin_headers, url, body).status_code == 409
    finish(task)
    r = patch(client, admin_headers, url, body)
    assert r.status_code == 200 and r.json[field] == value


def test_dataset_link_has_no_settings(client, admin_headers, project, global_dataset):
    c = Ctx("dataset", global_dataset)
    link_project(client, admin_headers, c, project)
    set_locked(project)
    assert patch(client, admin_headers, c.link(project.id), {"host": "x"}).status_code == 400
    assert patch(client, admin_headers, c.link(project.id), {}).status_code == 400


@by_kind
def test_global_patch_and_delete_need_every_linked_project_drained(ctx, client, admin_headers, project,
                                                                   other_project, make_task):
    """Only projects that link the resource gate it; a globally disabled resource makes links inactive."""
    gdisable = lambda on: patch(client, admin_headers, ctx.glob, {"enabled": on})  # noqa: E731
    link_project(client, admin_headers, ctx, project)
    set_locked(project)
    unrelated = make_task(project=other_project)  # in flight, but other_project has no link
    assert gdisable(False).status_code in (200, 202)
    assert gdisable(True).status_code in (200, 202)
    finish(unrelated)

    link_project(client, admin_headers, ctx, other_project)  # other_project stays unlocked
    assert gdisable(False).status_code == 409
    assert get(client, admin_headers, ctx.glob).json["enabled"] is True
    set_locked(other_project)
    task = make_task(project=other_project)
    assert gdisable(False).status_code == 409
    finish(task)
    r = gdisable(False)
    assert r.status_code in (200, 202) and r.json["enabled"] is False
    for p in (project, other_project):
        link = get(client, admin_headers, ctx.link(p.id)).json
        assert link["active"] is False and link["enabled"] is True and link["revoked"] is False
    assert gdisable(True).status_code in (200, 202)
    assert get(client, admin_headers, ctx.link(project.id)).json["active"] is True

    finish(task, "RUNNING")
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 409
    finish(task, "SUCCESS")  # succeeded with no result yet still counts as in flight
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 409
    finish(task, "FAILED")
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 204
    for p in (project, other_project):
        assert get(client, admin_headers, ctx.link(p.id)).status_code == 404


def test_global_delete_without_links_needs_no_lock(client, admin_headers, global_dataset):
    assert client.delete(f"/global/datasets/{global_dataset.id}", headers=admin_headers).status_code == 204


def test_secret_rotation_is_exempt_from_the_lock(client, admin_headers, k8s_client, project, other_project,
                                                 global_secret):
    c = Ctx("secret", global_secret)
    link_project(client, admin_headers, c, project)
    link_project(client, admin_headers, c, other_project)  # both unlocked
    assert patch(client, admin_headers, c.glob, {"values": {"TOKEN": "t2"}}).status_code == 200
    assert patch(client, admin_headers, c.glob, {"enabled": False}).status_code == 409  # turning it off is not


def test_two_projects_link_one_repo_independently(client, admin_headers, project, other_project, global_trigger_repo):
    """Revoking or disabling in one project never leaks into the other."""
    c = Ctx("trigger", global_trigger_repo)
    link_project(client, admin_headers, c, project)
    link_project(client, admin_headers, c, other_project)
    assert patch(client, admin_headers, c.link(project.id), {"revoked": True}).status_code == 200
    set_locked(other_project)
    assert patch(client, admin_headers, c.link(other_project.id), {"enabled": False}).status_code == 200
    assert get(client, admin_headers, c.link(project.id)).json["enabled"] is True
    other = get(client, admin_headers, c.link(other_project.id)).json
    assert other["revoked"] is False and other["active"] is False


def test_switching_a_repository_back_on_skips_the_gap(client, admin_headers, project, global_trigger_repo):
    """Pull requests merged before the repository was switched back on are stored but get no trigger; later ones do."""
    T = global_trigger_repo.id
    link = f"/projects/{project.id}/repositories/triggers/{T}"
    assert client.put(link, json={"watch_dir": "triggers"}, headers=admin_headers).status_code == 201
    # Start the link's cursor far back, so the first pull request is in its scope but for the re-enable
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

    set_locked(project)
    assert patch(client, admin_headers, f"{BASE}/{T}", {"enabled": False}).status_code == 200
    assert patch(client, admin_headers, f"{BASE}/{T}", {"enabled": True}).status_code == 200

    merged_before = datetime.utcnow() - timedelta(hours=1)
    merged_after = datetime.utcnow() + timedelta(days=1)
    r = client.post(f"{BASE}/{T}/pull_requests", headers=admin_headers, json={
        "pull_requests": [pull_request(1, merged_before), pull_request(2, merged_after)]
    })
    assert r.status_code == 201, r.json
    assert r.json["created"] == [1, 2]

    stored = get(client, admin_headers, f"{BASE}/{T}/pull_requests?per_page=50").json
    assert sorted(i["number"] for i in stored["items"]) == [1, 2]
    triggers = get(client, admin_headers, f"{link}/pull_requests?per_page=50").json
    assert [i["number"] for i in triggers["items"]] == [2]
