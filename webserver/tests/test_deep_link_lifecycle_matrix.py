"""
Lock / in-flight / enabled / revoked rules across the four project link kinds (secrets, datasets,
trigger repositories, results repositories), ADR 0019 sections 2, 9 and 11.

Every kind is driven through the same helpers, so one parametrized test covers all four.
"""
import pytest

from app.helpers.base_model import db

KINDS = ["secret", "dataset", "trigger", "results"]
IN_FLIGHT = ["PENDING", "QUEUED", "RUNNING"]


# --------------------------------------------------------------------------- helpers


class Ctx:
    """URLs and bodies of one link kind, for any project."""

    def __init__(self, kind, global_obj):
        self.kind = kind
        self.obj = global_obj

    def link(self, pid):
        if self.kind == "secret":
            return f"/projects/{pid}/secrets/{self.obj.label}"
        if self.kind == "dataset":
            return f"/projects/{pid}/datasets/{self.obj.id}"
        if self.kind == "trigger":
            return f"/projects/{pid}/repositories/triggers/{self.obj.id}"
        return f"/projects/{pid}/repositories/results/{self.obj.id}"

    @property
    def glob(self):
        if self.kind == "secret":
            return f"/global/secrets/{self.obj.label}"
        if self.kind == "dataset":
            return f"/global/datasets/{self.obj.id}"
        if self.kind == "trigger":
            return f"/global/repositories/triggers/{self.obj.id}"
        return f"/global/repositories/results/{self.obj.id}"

    @property
    def put_body(self):
        return {"trigger": {"watch_dir": "triggers"}, "results": {"target_dir": "results"}}.get(self.kind, {})

    @property
    def settings(self):
        """A settings-only PATCH body, or None when the kind has no project settings."""
        return {"trigger": {"watch_dir": "other"}, "results": {"target_dir": "out"}}.get(self.kind)

    @property
    def first_link_needs_lock(self):
        return self.kind == "results"


@pytest.fixture
def ctx(request, k8s_client):
    kind = request.param
    name = {"secret": "global_secret", "dataset": "global_dataset",
            "trigger": "global_trigger_repo", "results": "global_results_repo"}[kind]
    return Ctx(kind, request.getfixturevalue(name))


def by_kind(test):
    return pytest.mark.parametrize("ctx", KINDS, indirect=True)(test)


def set_locked(project, locked):
    project.locked = locked
    db.session.commit()


def link_project(client, admin_headers, c, project):
    """First PUT of the kind into the project (201), leaving the project unlocked."""
    was_locked = project.locked
    if c.first_link_needs_lock:
        set_locked(project, True)
    r = client.put(c.link(project.id), json=c.put_body, headers=admin_headers)
    assert r.status_code == 201, r.json
    set_locked(project, was_locked)
    return r.json


def finish(task, status="FAILED"):
    task.status = status
    db.session.commit()


def get(client, admin_headers, url):
    return client.get(url, headers=admin_headers)


def patch(client, admin_headers, url, body):
    return client.patch(url, json=body, headers=admin_headers)


# --------------------------------------------------------------------------- first link


@by_kind
def test_first_link_gate(ctx, client, admin_headers, project, make_task):
    """Linking needs no lock (201), except the results repository, which needs a drained project."""
    url = ctx.link(project.id)
    if ctx.first_link_needs_lock:
        assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 409
        set_locked(project, True)
        make_task()  # PENDING
        assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 409
        finish(make_task(), "FAILED")
    else:
        # a task in flight does not block a new watcher / grant
        make_task()
    if ctx.first_link_needs_lock:
        from app.models.task import Task
        for t in Task.query.all():
            finish(t, "FAILED")
    r = client.put(url, json=ctx.put_body, headers=admin_headers)
    assert r.status_code == 201, r.json
    assert r.json["active"] is True and r.json["enabled"] is True and r.json["revoked"] is False
    assert get(client, admin_headers, url).status_code == 200


# --------------------------------------------------------------------------- relink / delete gate


@by_kind
def test_relink_gate(ctx, client, admin_headers, project, make_task):
    """A second PUT (200) needs a locked project with nothing in flight."""
    link_project(client, admin_headers, ctx, project)
    url = ctx.link(project.id)
    assert client.put(url, json=ctx.put_body, headers=admin_headers).status_code == 409  # unlocked
    set_locked(project, True)
    task = make_task()
    r = client.put(url, json=ctx.put_body, headers=admin_headers)
    assert r.status_code == 409
    assert r.json["details"] == [task.id]
    finish(task, "FAILED")
    r = client.put(url, json=ctx.put_body, headers=admin_headers)
    assert r.status_code == 200, r.json
    assert r.json["active"] is True


@by_kind
def test_delete_gate_then_unlink(ctx, client, admin_headers, project, make_task):
    """DELETE of a link: 409 unlocked, 409 with a task in flight, 204 once drained, then 404."""
    link_project(client, admin_headers, ctx, project)
    url = ctx.link(project.id)
    assert client.delete(url, headers=admin_headers).status_code == 409
    set_locked(project, True)
    task = make_task()
    assert client.delete(url, headers=admin_headers).status_code == 409
    assert get(client, admin_headers, url).status_code == 200  # still linked
    finish(task, "CANCELED")
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert get(client, admin_headers, url).status_code == 404
    # the global resource survives an unlink
    assert get(client, admin_headers, ctx.glob).status_code == 200


@pytest.mark.parametrize("status,expected", [
    ("QUEUED", 409), ("RUNNING", 409),
    ("SUCCESS", 409),   # succeeded and no result yet: still needs the link (ADR section 9)
    ("FAILED", 204), ("CANCELED", 204),
])
def test_delete_dataset_link_by_task_status(client, admin_headers, project, global_dataset,
                                            make_task, status, expected):
    url = f"/projects/{project.id}/datasets/{global_dataset.id}"
    assert client.put(url, json={}, headers=admin_headers).status_code == 201
    set_locked(project, True)
    make_task(status=status)
    assert client.delete(url, headers=admin_headers).status_code == expected


# --------------------------------------------------------------------------- PATCH enabled


@by_kind
def test_patch_enabled_gate_and_active(ctx, client, admin_headers, project, make_task):
    link_project(client, admin_headers, ctx, project)
    url = ctx.link(project.id)
    assert patch(client, admin_headers, url, {"enabled": False}).status_code == 409  # unlocked
    set_locked(project, True)
    task = make_task()
    assert patch(client, admin_headers, url, {"enabled": False}).status_code == 409  # in flight
    finish(task, "FAILED")
    r = patch(client, admin_headers, url, {"enabled": False})
    assert r.status_code == 200, r.json
    assert r.json["enabled"] is False and r.json["active"] is False and r.json["revoked"] is False
    r = patch(client, admin_headers, url, {"enabled": True})
    assert r.status_code == 200
    assert r.json["active"] is True


@by_kind
def test_put_with_enabled_false_deactivates_on_relink(ctx, client, admin_headers, project):
    link_project(client, admin_headers, ctx, project)
    set_locked(project, True)
    r = client.put(ctx.link(project.id), json={**ctx.put_body, "enabled": False}, headers=admin_headers)
    assert r.status_code == 200, r.json
    assert r.json["enabled"] is False and r.json["active"] is False


def test_patch_settings_trigger_and_results_need_lock(client, admin_headers, project, global_trigger_repo,
                                                      make_task):
    c = Ctx("trigger", global_trigger_repo)
    link_project(client, admin_headers, c, project)
    url = c.link(project.id)
    assert patch(client, admin_headers, url, c.settings).status_code == 409
    set_locked(project, True)
    task = make_task()
    assert patch(client, admin_headers, url, c.settings).status_code == 409
    finish(task)
    r = patch(client, admin_headers, url, c.settings)
    assert r.status_code == 200 and r.json["watch_dir"] == "other"


def test_patch_settings_results_need_lock(client, admin_headers, project, global_results_repo, make_task):
    c = Ctx("results", global_results_repo)
    link_project(client, admin_headers, c, project)
    url = c.link(project.id)
    assert patch(client, admin_headers, url, c.settings).status_code == 409
    set_locked(project, True)
    task = make_task()
    assert patch(client, admin_headers, url, c.settings).status_code == 409
    finish(task)
    r = patch(client, admin_headers, url, c.settings)
    assert r.status_code == 200 and r.json["target_dir"] == "out"


@pytest.mark.parametrize("kind", ["secret", "dataset"])
def test_secret_and_dataset_links_have_no_settings(kind, client, admin_headers, project, global_secret,
                                                   global_dataset):
    c = Ctx(kind, global_secret if kind == "secret" else global_dataset)
    link_project(client, admin_headers, c, project)
    set_locked(project, True)
    assert patch(client, admin_headers, c.link(project.id), {"host": "x"}).status_code == 400
    assert patch(client, admin_headers, c.link(project.id), {}).status_code == 400


# --------------------------------------------------------------------------- revoked


@by_kind
def test_revoke_is_immediate_and_independent_of_lock_and_tasks(ctx, client, admin_headers, project, make_task):
    link_project(client, admin_headers, ctx, project)
    url = ctx.link(project.id)
    # project unlocked
    r = patch(client, admin_headers, url, {"revoked": True})
    assert r.status_code == 200, r.json
    assert r.json["revoked"] is True and r.json["active"] is False and r.json["enabled"] is True
    # the row is still returned (visibility contract)
    assert get(client, admin_headers, url).json["active"] is False
    # locked and with a task in flight: re-grant and revoke again are still immediate
    set_locked(project, True)
    make_task()
    r = patch(client, admin_headers, url, {"revoked": False})
    assert r.status_code == 200 and r.json["active"] is True
    r = patch(client, admin_headers, url, {"revoked": True})
    assert r.status_code == 200 and r.json["active"] is False


@by_kind
def test_unrevoke_restores_previous_enabled_state(ctx, client, admin_headers, project):
    """Revoke touches only `revoked`; a link disabled before stays disabled after the re-grant."""
    link_project(client, admin_headers, ctx, project)
    url = ctx.link(project.id)
    set_locked(project, True)
    assert patch(client, admin_headers, url, {"enabled": False}).status_code == 200
    assert patch(client, admin_headers, url, {"revoked": True}).json["enabled"] is False
    r = patch(client, admin_headers, url, {"revoked": False})
    assert r.json["enabled"] is False and r.json["active"] is False
    r = patch(client, admin_headers, url, {"enabled": True})
    assert r.json["active"] is True


@by_kind
def test_revoke_and_enabled_together_still_needs_lock(ctx, client, admin_headers, project):
    link_project(client, admin_headers, ctx, project)
    url = ctx.link(project.id)
    r = patch(client, admin_headers, url, {"revoked": True, "enabled": False})
    assert r.status_code == 409
    assert get(client, admin_headers, url).json["revoked"] is False  # nothing applied


def test_non_admin_cannot_revoke(client, post_json_user_header, admin_headers, project, global_dataset):
    c = Ctx("dataset", global_dataset)
    link_project(client, admin_headers, c, project)
    r = client.patch(c.link(project.id), json={"revoked": True}, headers=post_json_user_header)
    assert r.status_code == 403
    assert get(client, admin_headers, c.link(project.id)).json["revoked"] is False


# --------------------------------------------------------------------------- global enabled -> active


@by_kind
def test_global_disable_makes_link_inactive_but_keeps_link_flags(ctx, client, admin_headers, project):
    link_project(client, admin_headers, ctx, project)
    url = ctx.link(project.id)
    set_locked(project, True)
    r = patch(client, admin_headers, ctx.glob, {"enabled": False})
    assert r.status_code in (200, 202), r.json
    assert r.json["enabled"] is False
    link = get(client, admin_headers, url).json
    assert link["active"] is False and link["enabled"] is True and link["revoked"] is False
    r = patch(client, admin_headers, ctx.glob, {"enabled": True})
    assert r.status_code in (200, 202)
    assert get(client, admin_headers, url).json["active"] is True


@by_kind
def test_link_listing_includes_inactive_links(ctx, client, admin_headers, project):
    link_project(client, admin_headers, ctx, project)
    patch(client, admin_headers, ctx.link(project.id), {"revoked": True})
    base = {"secret": "secrets", "dataset": "datasets", "trigger": "repositories/triggers",
            "results": "repositories/results"}[ctx.kind]
    r = get(client, admin_headers, f"/projects/{project.id}/{base}")
    assert r.status_code == 200
    assert len(r.json) == 1 and r.json[0]["active"] is False


def test_trigger_active_link_filter_follows_every_flag(client, admin_headers, project, global_trigger_repo):
    """enabled project + enabled link + not revoked + enabled global repo => listed."""
    c = Ctx("trigger", global_trigger_repo)
    link_project(client, admin_headers, c, project)
    listing = "/global/repositories/triggers?active_link=true"
    ids = lambda: [r["id"] for r in get(client, admin_headers, listing).json]  # noqa: E731
    assert ids() == []  # project is disabled
    assert patch(client, admin_headers, f"/projects/{project.id}", {"locked": True}).status_code == 200
    assert patch(client, admin_headers, f"/projects/{project.id}", {"enabled": True}).status_code == 200
    assert ids() == [global_trigger_repo.id]
    patch(client, admin_headers, c.link(project.id), {"revoked": True})
    assert ids() == []
    patch(client, admin_headers, c.link(project.id), {"revoked": False})
    assert ids() == [global_trigger_repo.id]
    patch(client, admin_headers, c.link(project.id), {"enabled": False})
    assert ids() == []
    patch(client, admin_headers, c.link(project.id), {"enabled": True})
    assert patch(client, admin_headers, c.glob, {"enabled": False}).status_code == 200
    assert ids() == []


@by_kind
def test_project_enabled_flag_does_not_change_link_rules(ctx, client, admin_headers, project):
    """Enabling the project leaves the link's own flags alone, and relink works on an enabled project."""
    link_project(client, admin_headers, ctx, project)
    set_locked(project, True)
    assert patch(client, admin_headers, f"/projects/{project.id}", {"enabled": True}).status_code == 200
    r = client.put(ctx.link(project.id), json=ctx.put_body, headers=admin_headers)
    assert r.status_code == 200 and r.json["active"] is True
    assert patch(client, admin_headers, f"/projects/{project.id}", {"enabled": False}).status_code == 200
    assert get(client, admin_headers, ctx.link(project.id)).json["active"] is True


# --------------------------------------------------------------------------- global PATCH / DELETE vs other projects


@by_kind
def test_global_patch_needs_every_linked_project_drained(ctx, client, admin_headers, project, other_project,
                                                         make_task):
    link_project(client, admin_headers, ctx, project)
    link_project(client, admin_headers, ctx, other_project)
    set_locked(project, True)  # other_project stays unlocked
    r = patch(client, admin_headers, ctx.glob, {"enabled": False})
    assert r.status_code == 409
    assert get(client, admin_headers, ctx.glob).json["enabled"] is True
    set_locked(other_project, True)
    task = make_task(project=other_project)
    assert patch(client, admin_headers, ctx.glob, {"enabled": False}).status_code == 409
    finish(task)
    r = patch(client, admin_headers, ctx.glob, {"enabled": False})
    assert r.status_code in (200, 202), r.json
    for p in (project, other_project):
        assert get(client, admin_headers, ctx.link(p.id)).json["active"] is False


@by_kind
def test_global_delete_needs_every_linked_project_drained(ctx, client, admin_headers, project, other_project,
                                                          make_task):
    link_project(client, admin_headers, ctx, project)
    link_project(client, admin_headers, ctx, other_project)
    set_locked(project, True)
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 409
    set_locked(other_project, True)
    task = make_task(project=other_project, status="RUNNING")
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 409
    assert get(client, admin_headers, ctx.glob).status_code == 200
    finish(task, "SUCCESS")  # succeeded with no result yet still counts as in flight
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 409
    finish(task, "FAILED")
    assert client.delete(ctx.glob, headers=admin_headers).status_code == 204
    assert get(client, admin_headers, ctx.glob).status_code == 404
    for p in (project, other_project):
        assert get(client, admin_headers, ctx.link(p.id)).status_code == 404


@by_kind
def test_global_patch_ignores_unlinked_projects(ctx, client, admin_headers, project, other_project, make_task):
    """A project that does not use the resource does not gate it, locked or not, busy or not."""
    link_project(client, admin_headers, ctx, project)
    set_locked(project, True)
    make_task(project=other_project)  # in flight, but other_project has no link
    r = patch(client, admin_headers, ctx.glob, {"enabled": False})
    assert r.status_code in (200, 202), r.json


def test_global_delete_with_no_links_needs_no_lock(client, admin_headers, global_dataset):
    assert client.delete(f"/global/datasets/{global_dataset.id}", headers=admin_headers).status_code == 204


def test_secret_rotation_is_exempt_from_the_lock(client, admin_headers, k8s_client, project, other_project,
                                                 global_secret):
    c = Ctx("secret", global_secret)
    link_project(client, admin_headers, c, project)
    link_project(client, admin_headers, c, other_project)  # both unlocked
    r = patch(client, admin_headers, c.glob, {"values": {"TOKEN": "t2"}})
    assert r.status_code == 200, r.json
    # but turning it off is not
    assert patch(client, admin_headers, c.glob, {"enabled": False}).status_code == 409


def test_trigger_repo_secret_swap_is_exempt_but_uri_edit_is_not(client, admin_headers, project, other_project,
                                                                global_trigger_repo, global_secret):
    c = Ctx("trigger", global_trigger_repo)
    link_project(client, admin_headers, c, project)
    link_project(client, admin_headers, c, other_project)
    r = patch(client, admin_headers, c.glob, {"secret_label": "test-creds"})
    assert r.status_code == 200, r.json
    assert patch(client, admin_headers, c.glob, {"api_uri": "https://api.example.com"}).status_code == 409


def test_two_projects_link_one_global_resource_independently(client, admin_headers, project, other_project,
                                                             global_dataset):
    """Revoking or disabling in one project never leaks into the other."""
    c = Ctx("dataset", global_dataset)
    link_project(client, admin_headers, c, project)
    link_project(client, admin_headers, c, other_project)
    assert patch(client, admin_headers, c.link(project.id), {"revoked": True}).status_code == 200
    set_locked(other_project, True)
    assert patch(client, admin_headers, c.link(other_project.id), {"enabled": False}).status_code == 200
    assert get(client, admin_headers, c.link(project.id)).json["enabled"] is True
    assert get(client, admin_headers, c.link(other_project.id)).json["revoked"] is False
    assert get(client, admin_headers, c.link(other_project.id)).json["active"] is False


def test_results_repo_second_project_can_share_global_repo(client, admin_headers, project, other_project,
                                                           global_results_repo):
    c = Ctx("results", global_results_repo)
    link_project(client, admin_headers, c, project)
    link_project(client, admin_headers, c, other_project)
    # unlinking from the locked project leaves the other project's link
    set_locked(project, True)
    assert client.delete(c.link(project.id), headers=admin_headers).status_code == 204
    assert get(client, admin_headers, c.link(other_project.id)).status_code == 200
