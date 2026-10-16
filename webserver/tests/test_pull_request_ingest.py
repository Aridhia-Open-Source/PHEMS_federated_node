from app.helpers.base_model import db


def test_ingest_creates_and_fans_out(client, admin_headers, project, global_trigger_repo, linked_trigger_repo, make_pr_batch):
    T = global_trigger_repo.id
    ingest_url = f"/global/repositories/triggers/{T}/pull_requests"
    list_url = f"/projects/{project.id}/repositories/triggers/{T}/pull_requests"

    response = client.post(ingest_url, json=make_pr_batch(1, 2), headers=admin_headers)
    assert response.status_code == 201
    assert response.json == {"created": [1, 2], "existing": []}

    response = client.get(list_url, headers=admin_headers)
    assert response.status_code == 200
    assert response.json["total"] == 2
    assert all(item["state"] == "UNKNOWN" for item in response.json["items"])


def test_ingest_is_idempotent(client, admin_headers, project, global_trigger_repo, linked_trigger_repo, ingest_prs, make_pr_batch):
    T = global_trigger_repo.id
    ingest_prs(T, 1)

    response = client.post(f"/global/repositories/triggers/{T}/pull_requests", json=make_pr_batch(1, 2), headers=admin_headers)
    assert response.status_code == 201
    assert response.json["created"] == [2]
    assert response.json["existing"] == [1]

    response = client.get(f"/projects/{project.id}/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["total"] == 2


def test_other_base_branch_creates_no_trigger(client, admin_headers, project, global_trigger_repo, linked_trigger_repo, ingest_prs):
    T = global_trigger_repo.id
    ingest_prs(T, 3, base_branch="dev")

    response = client.get(f"/projects/{project.id}/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["total"] == 0


def test_file_outside_watch_dir_creates_no_trigger(client, admin_headers, project, global_trigger_repo, linked_trigger_repo, ingest_prs):
    T = global_trigger_repo.id
    ingest_prs(T, 4, changed_files=[{"path": "other/spec.json", "status": "added"}])

    response = client.get(f"/projects/{project.id}/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["total"] == 0


def test_non_matching_pr_leaves_link_empty_but_other_project_link_matches(
    client, admin_headers, project, other_project, global_trigger_repo, linked_trigger_repo, ingest_prs
):
    T = global_trigger_repo.id
    other = client.put(
        f"/projects/{other_project.id}/repositories/triggers/{T}", json={"watch_dir": "other"}, headers=admin_headers
    )
    assert other.status_code == 201
    ingest_prs(T, 6, changed_files=[{"path": "other/spec.json", "status": "added"}])

    mine = client.get(f"/projects/{project.id}/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert mine.json["total"] == 0
    theirs = client.get(f"/projects/{other_project.id}/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert theirs.json["total"] == 1
    assert theirs.json["items"][0]["state"] == "UNKNOWN"


def test_truncated_files_match(client, admin_headers, project, global_trigger_repo, linked_trigger_repo, ingest_prs):
    T = global_trigger_repo.id
    ingest_prs(T, 5, changed_files=[], files_truncated=True)

    response = client.get(f"/projects/{project.id}/repositories/triggers/{T}/pull_requests/5", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["state"] == "UNKNOWN"


def test_no_link_stores_but_no_triggers(client, admin_headers, global_trigger_repo, make_pr_batch):
    T = global_trigger_repo.id

    response = client.post(f"/global/repositories/triggers/{T}/pull_requests", json=make_pr_batch(1), headers=admin_headers)
    assert response.status_code == 201
    assert response.json["created"] == [1]

    response = client.get(f"/global/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["total"] == 1


def test_revoked_link_gets_no_trigger(client, admin_headers, project, global_trigger_repo, linked_trigger_repo, ingest_prs):
    T = global_trigger_repo.id

    response = client.patch(
        f"/projects/{project.id}/repositories/triggers/{T}", json={"revoked": True}, headers=admin_headers
    )
    assert response.status_code == 200

    ingest_prs(T, 1)

    response = client.get(f"/projects/{project.id}/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["total"] == 0


def test_disabled_repo_refused(client, admin_headers, global_trigger_repo, make_pr_batch):
    T = global_trigger_repo.id
    global_trigger_repo.enabled = False
    db.session.commit()

    response = client.post(f"/global/repositories/triggers/{T}/pull_requests", json=make_pr_batch(1), headers=admin_headers)
    assert response.status_code == 400
    assert "disabled" in response.json["error"]


def test_bad_bodies(client, admin_headers, global_trigger_repo, make_pr_batch):
    T = global_trigger_repo.id
    url = f"/global/repositories/triggers/{T}/pull_requests"

    response = client.post(url, json={"pull_requests": "x"}, headers=admin_headers)
    assert response.status_code == 400

    response = client.post(url, json=make_pr_batch(*range(1, 102)), headers=admin_headers)
    assert response.status_code == 400

    body = make_pr_batch(1)
    del body["pull_requests"][0]["title"]
    response = client.post(url, json=body, headers=admin_headers)
    assert response.status_code == 400


def test_unknown_repo(client, admin_headers, make_pr_batch):
    response = client.post(
        "/global/repositories/triggers/999/pull_requests", json=make_pr_batch(1), headers=admin_headers
    )
    assert response.status_code == 404
