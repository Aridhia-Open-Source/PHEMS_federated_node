def test_link_returns_201_and_lists(client, admin_headers, project, global_trigger_repo):
    url = f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}"

    put = client.put(url, json={"watch_dir": "triggers", "base_branch": "release"}, headers=admin_headers)
    assert put.status_code == 201
    assert put.json["watch_dir"] == "triggers"
    assert put.json["base_branch"] == "release"
    assert put.json["active"] is True
    assert put.json["trigger_repository"]["id"] == global_trigger_repo.id

    listing = client.get(f"/projects/{project.id}/repositories/triggers", headers=admin_headers)
    assert listing.status_code == 200
    assert len(listing.json) == 1


def test_active_filter_lists_only_active_links(client, admin_headers, project, global_trigger_repo, make_trigger_repo):
    other_trigger_repo = make_trigger_repo(uri="github.com/org/triggers2")
    base = f"/projects/{project.id}/repositories/triggers"
    for repo in (global_trigger_repo, other_trigger_repo):
        assert client.put(f"{base}/{repo.id}", json={"watch_dir": "t"}, headers=admin_headers).status_code == 201

    assert len(client.get(base, headers=admin_headers).json) == 2
    assert len(client.get(f"{base}?active=true", headers=admin_headers).json) == 2

    revoke = client.patch(f"{base}/{other_trigger_repo.id}", json={"revoked": True}, headers=admin_headers)
    assert revoke.status_code == 200

    assert len(client.get(base, headers=admin_headers).json) == 2
    active = client.get(f"{base}?active=true", headers=admin_headers)
    assert active.status_code == 200
    assert [l["trigger_repository"]["id"] for l in active.json] == [global_trigger_repo.id]


def test_active_filter_omits_disabled_link(client, admin_headers, project, global_trigger_repo, lock_project):
    base = f"/projects/{project.id}/repositories/triggers"
    assert client.put(f"{base}/{global_trigger_repo.id}", json={"watch_dir": "t"}, headers=admin_headers).status_code == 201
    disable = client.patch(f"{base}/{global_trigger_repo.id}", json={"enabled": False}, headers=admin_headers)
    assert disable.status_code == 200

    assert len(client.get(base, headers=admin_headers).json) == 1
    assert client.get(f"{base}?active=true", headers=admin_headers).json == []


def test_link_bad_body(client, admin_headers, project, global_trigger_repo):
    url = f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}"

    empty = client.put(url, json={}, headers=admin_headers)
    assert empty.status_code == 400

    bogus = client.put(url, json={"watch_dir": "x", "bogus": 1}, headers=admin_headers)
    assert bogus.status_code == 400


def test_link_unknown_repo_or_project(client, admin_headers, project, global_trigger_repo):
    unknown_repo = client.put(
        f"/projects/{project.id}/repositories/triggers/999", json={"watch_dir": "x"}, headers=admin_headers
    )
    assert unknown_repo.status_code == 404

    unknown_project = client.put(
        f"/projects/999/repositories/triggers/{global_trigger_repo.id}", json={"watch_dir": "x"},
        headers=admin_headers
    )
    assert unknown_project.status_code == 404


def test_relink_needs_lock(client, admin_headers, linked_trigger_repo):
    url = (f"/projects/{linked_trigger_repo['project_id']}"
           f"/repositories/triggers/{linked_trigger_repo['trigger_repository']['id']}")

    response = client.put(url, json={"watch_dir": "other"}, headers=admin_headers)
    assert response.status_code == 409


def test_relink_locked_returns_200(client, admin_headers, linked_trigger_repo, lock_project):
    url = (f"/projects/{linked_trigger_repo['project_id']}"
           f"/repositories/triggers/{linked_trigger_repo['trigger_repository']['id']}")

    response = client.put(url, json={"watch_dir": "other"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["watch_dir"] == "other"


def test_other_project_cannot_see_link(client, admin_headers, linked_trigger_repo, other_project):
    repo_id = linked_trigger_repo["trigger_repository"]["id"]

    response = client.get(
        f"/projects/{other_project.id}/repositories/triggers/{repo_id}", headers=admin_headers
    )
    assert response.status_code == 404


def test_revoke_admin_only(client, admin_headers, post_json_user_header, linked_trigger_repo):
    url = (f"/projects/{linked_trigger_repo['project_id']}"
           f"/repositories/triggers/{linked_trigger_repo['trigger_repository']['id']}")

    forbidden = client.patch(url, json={"revoked": True}, headers=post_json_user_header)
    assert forbidden.status_code == 403

    revoked = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert revoked.status_code == 200
    assert revoked.json["revoked"] is True
    assert revoked.json["active"] is False


def test_unrevoke_backfills(client, admin_headers, linked_trigger_repo, ingest_prs):
    repo_id = linked_trigger_repo["trigger_repository"]["id"]
    url = f"/projects/{linked_trigger_repo['project_id']}/repositories/triggers/{repo_id}"

    revoke = client.patch(url, json={"revoked": True}, headers=admin_headers)
    assert revoke.status_code == 200

    ingest_prs(repo_id, 1)

    restore = client.patch(url, json={"revoked": False}, headers=admin_headers)
    assert restore.status_code == 200
    assert restore.json["active"] is True
    assert restore.json["pr_count"] == 1


def test_disable_needs_lock_and_no_tasks_in_flight(
    client, admin_headers, linked_trigger_repo, lock_project, make_task
):
    url = (f"/projects/{linked_trigger_repo['project_id']}"
           f"/repositories/triggers/{linked_trigger_repo['trigger_repository']['id']}")

    disable = client.patch(url, json={"enabled": False}, headers=admin_headers)
    assert disable.status_code == 200
    assert disable.json["enabled"] is False

    task = make_task()

    enable = client.patch(url, json={"enabled": True}, headers=admin_headers)
    assert enable.status_code == 409
    assert enable.json["details"] == [task.id]


def test_unlink(client, admin_headers, linked_trigger_repo, lock_project):
    url = (f"/projects/{linked_trigger_repo['project_id']}"
           f"/repositories/triggers/{linked_trigger_repo['trigger_repository']['id']}")

    deleted = client.delete(url, headers=admin_headers)
    assert deleted.status_code == 204

    gone = client.get(url, headers=admin_headers)
    assert gone.status_code == 404
