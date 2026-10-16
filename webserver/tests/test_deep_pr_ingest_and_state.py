"""
Deep tests of pull request ingest, fan-out and the per-link trigger state (ADR 0019 sections 3 and 11).
"""
import pytest

from app.helpers.base_model import db

MERGED = "2030-01-01T10:00:00Z"


def pr(number=1, /, **fields) -> dict:
    body = {
        "number": number, "title": f"PR {number}", "raised_by": "user1", "merged_at": MERGED,
        "merge_commit_sha": (f"{number}" * 40)[:40], "base_branch": "main", "files_truncated": False,
        "changed_files": [{"path": "triggers/spec.json", "status": "added"}],
    }
    body.update(fields)
    return body


def files(*paths, status="added") -> list:
    return [{"path": p, "status": status} for p in paths]


def post_prs(client, headers, repo_id, *prs):
    return client.post(
        f"/global/repositories/triggers/{repo_id}/pull_requests", json={"pull_requests": list(prs)}, headers=headers
    )


def link(client, headers, pid, repo_id, **body):
    body.setdefault("watch_dir", "triggers")
    response = client.put(f"/projects/{pid}/repositories/triggers/{repo_id}", json=body, headers=headers)
    assert response.status_code in (200, 201), response.json
    return response


def trig_url(pid, repo_id, number=None):
    base = f"/projects/{pid}/repositories/triggers/{repo_id}/pull_requests"
    return base if number is None else f"{base}/{number}"


def states(client, headers, pid, repo_id) -> dict:
    response = client.get(trig_url(pid, repo_id) + "?per_page=200", headers=headers)
    assert response.status_code == 200, response.json
    return {i["number"]: i["state"] for i in response.json["items"]}


def get_trigger(client, headers, pid, repo_id, number):
    response = client.get(trig_url(pid, repo_id, number), headers=headers)
    assert response.status_code == 200, response.json
    return response.json


def one_state(client, admin_headers, project, repo, **fields):
    """Link with watch_dir triggers, ingest PR 1 with fields, return its trigger."""
    link(client, admin_headers, project.id, repo.id)
    r = post_prs(client, admin_headers, repo.id, pr(1, **fields))
    assert r.status_code == 201, r.json
    return get_trigger(client, admin_headers, project.id, repo.id, 1)


# ---------------------------------------------------------------- cursor semantics

def test_prs_ingested_before_link_get_no_trigger(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    assert post_prs(client, admin_headers, T, pr(1), pr(2)).status_code == 201
    response = link(client, admin_headers, project.id, T)
    assert response.status_code == 201
    assert response.json["pr_count"] == 0
    assert states(client, admin_headers, project.id, T) == {}


def test_pr_merged_later_than_latest_stored_is_triggered_after_link(
    client, admin_headers, project, global_trigger_repo
):
    T = global_trigger_repo.id
    post_prs(client, admin_headers, T, pr(1))
    link(client, admin_headers, project.id, T)
    r = post_prs(client, admin_headers, T, pr(2, merged_at="2030-01-02T10:00:00Z"))
    assert r.json == {"created": [2], "existing": []}
    assert states(client, admin_headers, project.id, T) == {2: "UNKNOWN"}


def test_pr_merged_before_link_cursor_is_not_triggered(client, admin_headers, project, global_trigger_repo):
    """The cursor is the latest stored PR; an older one arriving late is out of scope."""
    T = global_trigger_repo.id
    post_prs(client, admin_headers, T, pr(5))
    link(client, admin_headers, project.id, T)
    post_prs(client, admin_headers, T, pr(6, merged_at="2029-12-31T10:00:00Z"))
    assert states(client, admin_headers, project.id, T) == {}


def test_cursor_tie_on_merged_at_is_broken_by_number(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    post_prs(client, admin_headers, T, pr(5))
    link(client, admin_headers, project.id, T)
    # same merged_at as the cursor: only a higher number is after it
    post_prs(client, admin_headers, T, pr(4), pr(6))
    assert states(client, admin_headers, project.id, T) == {6: "UNKNOWN"}


def test_pr_merged_in_the_past_after_link_with_nothing_stored_is_out_of_scope(
    client, admin_headers, project, global_trigger_repo
):
    """With nothing stored, the cursor is the link's creation time, so history is not replayed."""
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    post_prs(client, admin_headers, T, pr(1, merged_at="2020-01-01T00:00:00Z"))
    assert states(client, admin_headers, project.id, T) == {}


def test_relink_put_does_not_replay_or_move_cursor(client, admin_headers, project, global_trigger_repo, lock_project):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    post_prs(client, admin_headers, T, pr(1))
    before = client.get(f"/projects/{project.id}/repositories/triggers/{T}", headers=admin_headers).json
    r = client.put(
        f"/projects/{project.id}/repositories/triggers/{T}", json={"watch_dir": "triggers"}, headers=admin_headers
    )
    assert r.status_code == 200
    assert r.json["pr_count"] == before["pr_count"] == 1
    assert r.json["pr_cursor"] == before["pr_cursor"]
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}


def test_unrevoke_backfills_missed_prs(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    url = f"/projects/{project.id}/repositories/triggers/{T}"
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    post_prs(client, admin_headers, T, pr(1), pr(2, changed_files=files("elsewhere/a.json")))
    assert states(client, admin_headers, project.id, T) == {}
    r = client.patch(url, json={"revoked": False}, headers=admin_headers)
    assert r.status_code == 200 and r.json["pr_count"] == 2
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 2: "IGNORED"}


def test_unrevoke_does_not_backfill_prs_older_than_link(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    post_prs(client, admin_headers, T, pr(1))
    link(client, admin_headers, project.id, T)
    url = f"/projects/{project.id}/repositories/triggers/{T}"
    client.patch(url, json={"revoked": True}, headers=admin_headers)
    r = client.patch(url, json={"revoked": False}, headers=admin_headers)
    assert r.status_code == 200 and r.json["pr_count"] == 0


def test_unrevoke_twice_does_not_duplicate_triggers(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    url = f"/projects/{project.id}/repositories/triggers/{T}"
    client.patch(url, json={"revoked": True}, headers=admin_headers)
    post_prs(client, admin_headers, T, pr(1))
    client.patch(url, json={"revoked": False}, headers=admin_headers)
    client.patch(url, json={"revoked": True}, headers=admin_headers)
    r = client.patch(url, json={"revoked": False}, headers=admin_headers)
    assert r.json["pr_count"] == 1


def test_disabled_link_gets_no_trigger_until_reenabled(
    client, admin_headers, project, global_trigger_repo, lock_project
):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    url = f"/projects/{project.id}/repositories/triggers/{T}"
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).status_code == 200
    post_prs(client, admin_headers, T, pr(1))
    assert states(client, admin_headers, project.id, T) == {}
    r = client.patch(url, json={"enabled": True}, headers=admin_headers)
    assert r.status_code == 200
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}


def test_link_created_disabled_gets_no_trigger_then_put_enable_backfills(
    client, admin_headers, project, global_trigger_repo, lock_project
):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T, enabled=False)
    post_prs(client, admin_headers, T, pr(1))
    assert states(client, admin_headers, project.id, T) == {}
    r = client.put(
        f"/projects/{project.id}/repositories/triggers/{T}", json={"watch_dir": "triggers"}, headers=admin_headers
    )
    assert r.status_code == 200
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}


def test_disabled_project_link_still_gets_triggers(client, admin_headers, project, global_trigger_repo):
    """The fixture project is disabled; ADR 3 fans out to active links (link flags, not project.enabled)."""
    assert project.enabled is False
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    post_prs(client, admin_headers, T, pr(1))
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}


def test_enabling_global_repo_after_disable_backfills_nothing_for_refused_batch(
    client, admin_headers, project, global_trigger_repo
):
    """A disabled repository stores nothing, so nothing exists to backfill after it is re-enabled."""
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    global_trigger_repo.enabled = False
    db.session.commit()
    r = post_prs(client, admin_headers, T, pr(1))
    assert r.status_code == 400 and "disabled" in r.json["error"]
    global_trigger_repo.enabled = True
    db.session.commit()
    g = client.get(f"/global/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert g.json["total"] == 0


# ---------------------------------------------------------------- idempotence, batch sizes

def test_reingest_across_batches_is_idempotent(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    assert post_prs(client, admin_headers, T, pr(1), pr(2)).json == {"created": [1, 2], "existing": []}
    assert post_prs(client, admin_headers, T, pr(2), pr(3)).json == {"created": [3], "existing": [2]}
    assert post_prs(client, admin_headers, T, pr(1), pr(2), pr(3)).json == {"created": [], "existing": [1, 2, 3]}
    assert len(states(client, admin_headers, project.id, T)) == 3


def test_reingest_does_not_change_facts_or_state(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    post_prs(client, admin_headers, T, pr(1, title="original"))
    url = trig_url(project.id, T, 1)
    client.patch(url, json={"state": "REJECTED", "state_cause": "bad"}, headers=admin_headers)
    r = post_prs(client, admin_headers, T, pr(1, title="changed", base_branch="dev", changed_files=[]))
    assert r.json == {"created": [], "existing": [1]}
    t = get_trigger(client, admin_headers, project.id, T, 1)
    assert t["state"] == "REJECTED" and t["state_cause"] == "bad" and t["title"] == "original"
    g = client.get(f"/global/repositories/triggers/{T}/pull_requests", headers=admin_headers).json
    assert g["items"][0]["title"] == "original" and g["items"][0]["base_branch"] == "main"


def test_exactly_100_prs_accepted(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    r = post_prs(client, admin_headers, T, *[pr(n) for n in range(1, 101)])
    assert r.status_code == 201
    assert r.json["created"] == list(range(1, 101))
    g = client.get(f"/projects/{project.id}/repositories/triggers/{T}/pull_requests?per_page=1", headers=admin_headers)
    assert g.json["total"] == 100


def test_101_prs_refused_and_nothing_stored(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    r = post_prs(client, admin_headers, T, *[pr(n) for n in range(1, 102)])
    assert r.status_code == 400
    g = client.get(f"/global/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert g.json["total"] == 0


def test_empty_batch_is_accepted(client, admin_headers, global_trigger_repo):
    r = post_prs(client, admin_headers, global_trigger_repo.id)
    assert r.status_code == 201
    assert r.json == {"created": [], "existing": []}


def test_duplicate_numbers_inside_one_batch(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    r = post_prs(client, admin_headers, T, pr(1, title="first"), pr(1, title="second"), pr(2))
    assert r.status_code == 201, r.json
    assert r.json == {"created": [1, 2], "existing": [1]}
    assert get_trigger(client, admin_headers, project.id, T, 1)["title"] == "first"
    assert len(states(client, admin_headers, project.id, T)) == 2


def test_invalid_pr_in_batch_refuses_whole_batch(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    bad = pr(2)
    del bad["title"]
    assert post_prs(client, admin_headers, T, pr(1), bad).status_code == 400
    assert states(client, admin_headers, project.id, T) == {}


# ---------------------------------------------------------------- file matching

@pytest.mark.parametrize("watch_dir, paths, expected", [
    ("triggers", ["triggers/spec.json"], "UNKNOWN"),
    ("triggers", ["triggers/nested/deep/spec.json"], "UNKNOWN"),
    ("triggers", ["triggers-old/spec.json"], "IGNORED"),
    ("triggers", ["old-triggers/spec.json"], "IGNORED"),
    ("triggers", ["other/triggers/spec.json"], "IGNORED"),
    ("triggers", ["spec.json"], "IGNORED"),
    ("triggers", ["triggers/readme.md"], "IGNORED"),
    ("triggers", ["triggers/readme.md", "triggers/x.json"], "UNKNOWN"),
    ("triggers/a", ["triggers/spec.json"], "IGNORED"),
    ("triggers/a", ["triggers/a/spec.json"], "UNKNOWN"),
    ("triggers/a", ["triggers/ab/spec.json"], "IGNORED"),
    ("/triggers/", ["triggers/spec.json"], "UNKNOWN"),
    ("./triggers", ["triggers/spec.json"], "UNKNOWN"),
    ("", ["anything/at/all.json"], "UNKNOWN"),
    ("", ["root.json"], "UNKNOWN"),
])
def test_file_matching_against_watch_dir(client, admin_headers, project, global_trigger_repo, watch_dir, paths, expected):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T, watch_dir=watch_dir)
    r = post_prs(client, admin_headers, T, pr(1, changed_files=files(*paths)))
    assert r.status_code == 201, r.json
    t = get_trigger(client, admin_headers, project.id, T, 1)
    assert t["state"] == expected
    if expected == "IGNORED":
        assert t["state_cause"]
    else:
        assert t["state_cause"] is None


@pytest.mark.parametrize("status", ["removed", "deleted", "renamed", "modified"])
def test_only_added_spec_files_match(client, admin_headers, project, global_trigger_repo, status):
    """Dagster's rule: a file the PR adds. Deleted/renamed/modified specs do not trigger a run."""
    t = one_state(client, admin_headers, project, global_trigger_repo,
                  changed_files=files("triggers/spec.json", status=status))
    assert t["state"] == "IGNORED"


def test_multiple_files_one_matching_is_enough(client, admin_headers, project, global_trigger_repo):
    t = one_state(client, admin_headers, project, global_trigger_repo, changed_files=[
        {"path": "triggers/old.json", "status": "removed"},
        {"path": "docs/readme.md", "status": "added"},
        {"path": "triggers/new.json", "status": "added"},
    ])
    assert t["state"] == "UNKNOWN"


def test_empty_changed_files_is_ignored(client, admin_headers, project, global_trigger_repo):
    t = one_state(client, admin_headers, project, global_trigger_repo, changed_files=[])
    assert t["state"] == "IGNORED"
    assert "triggers" in t["state_cause"]


def test_files_truncated_matches_every_path(client, admin_headers, project, global_trigger_repo):
    t = one_state(client, admin_headers, project, global_trigger_repo,
                  files_truncated=True, changed_files=files("unrelated/file.txt"))
    assert t["state"] == "UNKNOWN"


def test_files_truncated_still_respects_base_branch(client, admin_headers, project, global_trigger_repo):
    t = one_state(client, admin_headers, project, global_trigger_repo, files_truncated=True, base_branch="dev")
    assert t["state"] == "IGNORED"
    assert "dev" in t["state_cause"]


def test_ignored_cause_names_watch_dir(client, admin_headers, project, global_trigger_repo):
    link(client, admin_headers, project.id, global_trigger_repo.id, watch_dir="specs/here")
    post_prs(client, admin_headers, global_trigger_repo.id, pr(1))
    t = get_trigger(client, admin_headers, project.id, global_trigger_repo.id, 1)
    assert t["state"] == "IGNORED" and "specs/here" in t["state_cause"]


# ---------------------------------------------------------------- base branch

def test_base_branch_defaults_to_main(client, admin_headers, project, global_trigger_repo):
    r = link(client, admin_headers, project.id, global_trigger_repo.id)
    assert r.json["base_branch"] == "main"
    post_prs(client, admin_headers, global_trigger_repo.id, pr(1), pr(2, base_branch="master"))
    assert states(client, admin_headers, project.id, global_trigger_repo.id) == {1: "UNKNOWN", 2: "IGNORED"}


def test_base_branch_override_matches_only_that_branch(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T, base_branch="release/1.0")
    post_prs(client, admin_headers, T, pr(1, base_branch="release/1.0"), pr(2), pr(3, base_branch="release"))
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 2: "IGNORED", 3: "IGNORED"}
    assert "release/1.0" in get_trigger(client, admin_headers, project.id, T, 2)["state_cause"]


def test_base_branch_is_case_sensitive(client, admin_headers, project, global_trigger_repo):
    t = one_state(client, admin_headers, project, global_trigger_repo, base_branch="Main")
    assert t["state"] == "IGNORED"


# ---------------------------------------------------------------- multiple projects / links

def test_two_projects_one_repo_get_independent_triggers(
    client, admin_headers, project, other_project, global_trigger_repo
):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T, watch_dir="triggers")
    link(client, admin_headers, other_project.id, T, watch_dir="other", base_branch="dev")
    r = post_prs(client, admin_headers, T, pr(1), pr(2, base_branch="dev", changed_files=files("other/x.json")))
    assert r.json["created"] == [1, 2]
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 2: "IGNORED"}
    assert states(client, admin_headers, other_project.id, T) == {1: "IGNORED", 2: "UNKNOWN"}
    # state changes do not leak across projects
    client.patch(trig_url(project.id, T, 1), json={"state": "REJECTED", "state_cause": "x"}, headers=admin_headers)
    assert get_trigger(client, admin_headers, other_project.id, T, 1)["state"] == "IGNORED"
    assert get_trigger(client, admin_headers, project.id, T, 1)["project_id"] == project.id
    g = client.get(f"/global/repositories/triggers/{T}/pull_requests", headers=admin_headers)
    assert g.json["total"] == 2


def test_pr_ingested_twice_for_two_links_creates_one_pr_two_triggers(
    client, admin_headers, project, other_project, global_trigger_repo
):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    first = post_prs(client, admin_headers, T, pr(1))
    link(client, admin_headers, other_project.id, T)  # cursor now after PR 1
    second = post_prs(client, admin_headers, T, pr(1))
    assert first.json == {"created": [1], "existing": []}
    assert second.json == {"created": [], "existing": [1]}
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}
    assert states(client, admin_headers, other_project.id, T) == {}


def test_second_link_later_does_not_get_earlier_prs_but_gets_new_ones(
    client, admin_headers, project, other_project, global_trigger_repo
):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    post_prs(client, admin_headers, T, pr(1))
    link(client, admin_headers, other_project.id, T)
    post_prs(client, admin_headers, T, pr(2, merged_at="2030-02-01T00:00:00Z"))
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 2: "UNKNOWN"}
    assert states(client, admin_headers, other_project.id, T) == {2: "UNKNOWN"}


def test_revoked_link_of_one_project_does_not_affect_the_other(
    client, admin_headers, project, other_project, global_trigger_repo
):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    link(client, admin_headers, other_project.id, T)
    client.patch(f"/projects/{project.id}/repositories/triggers/{T}", json={"revoked": True}, headers=admin_headers)
    post_prs(client, admin_headers, T, pr(1))
    assert states(client, admin_headers, project.id, T) == {}
    assert states(client, admin_headers, other_project.id, T) == {1: "UNKNOWN"}


# ---------------------------------------------------------------- trigger state PATCH

def test_patch_state_legal_transitions(client, admin_headers, pr_trigger):
    cases = [
        ({"state": "IGNORED", "state_cause": "not ours"}, "IGNORED", "not ours"),
        ({"state": "REJECTED", "state_cause": "bad spec"}, "REJECTED", "bad spec"),
        ({"state": "UNKNOWN"}, "UNKNOWN", None),
        ({"state": "YIELDED"}, "YIELDED", None),
    ]
    for body, state, cause in cases:
        r = client.patch(pr_trigger, json=body, headers=admin_headers)
        assert r.status_code == 200, (body, r.json)
        assert r.json["state"] == state and r.json["state_cause"] == cause


@pytest.mark.parametrize("body", [
    {"state": "IGNORED"},
    {"state": "REJECTED"},
    {"state": "REJECTED", "state_cause": ""},
    {"state": "UNKNOWN", "state_cause": "no cause allowed"},
    {"state": "YIELDED", "state_cause": "no cause allowed"},
    {"state": "BOGUS"},
    {"state": "unknown"},
    {"state": ""},
    {"state": None},
    {"state": 1},
])
def test_patch_state_illegal_bodies_are_400_and_change_nothing(client, admin_headers, pr_trigger, body):
    r = client.patch(pr_trigger, json=body, headers=admin_headers)
    assert r.status_code == 400, r.json
    assert client.get(pr_trigger, headers=admin_headers).json["state"] == "UNKNOWN"


def test_patch_state_cause_alone_on_unknown_is_refused(client, admin_headers, pr_trigger):
    assert client.patch(pr_trigger, json={"state_cause": "why"}, headers=admin_headers).status_code == 400


def test_patch_cause_alone_updates_cause_of_rejected(client, admin_headers, pr_trigger):
    client.patch(pr_trigger, json={"state": "REJECTED", "state_cause": "old"}, headers=admin_headers)
    r = client.patch(pr_trigger, json={"state_cause": "new"}, headers=admin_headers)
    assert r.status_code == 200 and r.json["state"] == "REJECTED" and r.json["state_cause"] == "new"


def test_patch_leaving_ignored_clears_cause(client, admin_headers, project, global_trigger_repo):
    t = one_state(client, admin_headers, project, global_trigger_repo, base_branch="dev")
    assert t["state"] == "IGNORED"
    url = trig_url(project.id, global_trigger_repo.id, 1)
    r = client.patch(url, json={"state": "UNKNOWN"}, headers=admin_headers)
    assert r.status_code == 200 and r.json["state_cause"] is None


def test_patch_empty_body_changes_nothing(client, admin_headers, pr_trigger):
    r = client.patch(pr_trigger, json={}, headers=admin_headers)
    assert r.status_code == 200 and r.json["state"] == "UNKNOWN"


def test_patch_cannot_change_immutable_facts(client, admin_headers, pr_trigger):
    r = client.patch(pr_trigger, json={"title": "hacked", "task_id": 5}, headers=admin_headers)
    assert r.status_code in (200, 400)
    t = client.get(pr_trigger, headers=admin_headers).json
    assert t["title"] == "PR 1" and t["task_id"] is None


def test_patch_trigger_of_other_project_is_404(client, admin_headers, other_project, global_trigger_repo, pr_trigger):
    T = global_trigger_repo.id
    url = trig_url(other_project.id, T, 1)
    assert client.patch(url, json={"state": "UNKNOWN"}, headers=admin_headers).status_code == 404
    assert client.get(url, headers=admin_headers).status_code == 404


def test_trigger_fields_expose_pr_facts(client, admin_headers, pr_trigger, global_trigger_repo, project):
    t = client.get(pr_trigger, headers=admin_headers).json
    assert t["number"] == 1 and t["raised_by"] == "user1" and t["merge_commit_sha"] == "1" * 40
    assert t["trigger_repository_id"] == global_trigger_repo.id and t["project_id"] == project.id
    assert t["merged_at"].startswith("2030-01-01T10:00:00")


# ---------------------------------------------------------------- merged_at formats

@pytest.mark.parametrize("merged_at", [
    "2030-01-01T10:00:00Z",
    "2030-01-01T10:00:00",
    "2030-01-01T10:00:00.123456Z",
    "2030-01-01T10:00:00+00:00",
    "2030-01-01",
])
def test_merged_at_accepted_formats(client, admin_headers, project, global_trigger_repo, merged_at):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    r = post_prs(client, admin_headers, T, pr(1, merged_at=merged_at))
    assert r.status_code == 201, r.json
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}


def test_merged_at_with_offset_is_converted_to_utc(client, admin_headers, global_trigger_repo):
    T = global_trigger_repo.id
    r = post_prs(client, admin_headers, T, pr(1, merged_at="2030-01-01T12:00:00+02:00"))
    assert r.status_code == 201, r.json
    g = client.get(f"/global/repositories/triggers/{T}/pull_requests", headers=admin_headers).json
    assert g["items"][0]["merged_at"].startswith("2030-01-01T10:00:00")


@pytest.mark.parametrize("merged_at", ["", "yesterday", "2030-13-45T00:00:00Z", 1893492000, None, ["2030-01-01"]])
def test_merged_at_invalid_values_are_400(client, admin_headers, global_trigger_repo, merged_at):
    r = post_prs(client, admin_headers, global_trigger_repo.id, pr(1, merged_at=merged_at))
    assert r.status_code == 400, r.json


def test_merged_at_boundary_equal_to_cursor_uses_number(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    post_prs(client, admin_headers, T, pr(10, merged_at="2030-05-05T05:05:05Z"))
    link(client, admin_headers, project.id, T)
    post_prs(client, admin_headers, T,
             pr(10, merged_at="2030-05-05T05:05:05Z"),          # already stored
             pr(11, merged_at="2030-05-05T05:05:05Z"),          # same second, higher number: in
             pr(12, merged_at="2030-05-05T05:05:04Z"))          # a second earlier: out
    assert states(client, admin_headers, project.id, T) == {11: "UNKNOWN"}


def test_pr_cursor_follows_latest_trigger_merge(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    post_prs(client, admin_headers, T, pr(1, merged_at="2030-03-03T03:03:03Z"))
    r = client.get(f"/projects/{project.id}/repositories/triggers/{T}", headers=admin_headers)
    assert r.json["pr_cursor"] == "2030-03-03T03:03:03Z"
    assert client.get(f"/global/repositories/triggers/{T}", headers=admin_headers).json["pr_cursor"] \
        == "2030-03-03T03:03:03Z"


# ---------------------------------------------------------------- malformed bodies

def test_body_without_pull_requests_key(client, admin_headers, global_trigger_repo):
    r = client.post(f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests",
                    json={}, headers=admin_headers)
    assert r.status_code == 400


@pytest.mark.parametrize("value", ["x", 1, None, {"number": 1}, True])
def test_pull_requests_must_be_a_list(client, admin_headers, global_trigger_repo, value):
    r = client.post(f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests",
                    json={"pull_requests": value}, headers=admin_headers)
    assert r.status_code == 400


@pytest.mark.parametrize("field", [
    "number", "title", "raised_by", "merged_at", "merge_commit_sha", "base_branch", "files_truncated", "changed_files",
])
def test_missing_required_field_is_400(client, admin_headers, global_trigger_repo, field):
    body = pr(1)
    del body[field]
    assert post_prs(client, admin_headers, global_trigger_repo.id, body).status_code == 400


def test_extra_field_in_pr_is_400(client, admin_headers, global_trigger_repo):
    assert post_prs(client, admin_headers, global_trigger_repo.id, pr(1, bogus=1)).status_code == 400


def test_extra_field_in_changed_file_is_400(client, admin_headers, global_trigger_repo):
    r = post_prs(client, admin_headers, global_trigger_repo.id,
                 pr(1, changed_files=[{"path": "triggers/a.json", "status": "added", "content": "{}"}]))
    assert r.status_code == 400


@pytest.mark.parametrize("fields", [
    {"number": "1"}, {"number": 1.5}, {"number": True}, {"number": None},
    {"title": 5}, {"title": None}, {"raised_by": 5},
    {"merge_commit_sha": 5}, {"merge_commit_sha": ""}, {"merge_commit_sha": "a" * 41},
    {"base_branch": ""}, {"base_branch": 5},
    {"files_truncated": "false"}, {"files_truncated": 0}, {"files_truncated": None},
    {"changed_files": "triggers/a.json"}, {"changed_files": None},
    {"changed_files": ["triggers/a.json"]},
    {"changed_files": [{"path": "", "status": "added"}]},
    {"changed_files": [{"path": "a.json"}]},
    {"changed_files": [{"path": 5, "status": "added"}]},
    {"changed_files": [{"path": "a.json", "status": ""}]},
    {"title": "t" * 257},
])
def test_wrong_typed_or_out_of_range_fields_are_400(client, admin_headers, global_trigger_repo, fields):
    r = post_prs(client, admin_headers, global_trigger_repo.id, pr(1, **fields))
    assert r.status_code == 400, r.json


@pytest.mark.xfail(reason="PullRequestRequest.number has no ge=1 bound: 0 and -1 are stored (201)", strict=False)
@pytest.mark.parametrize("number", [0, -1])
def test_non_positive_pr_number_is_refused(client, admin_headers, global_trigger_repo, number):
    """PR numbers start at 1 at the provider; 0 and negatives are not real numbers."""
    assert post_prs(client, admin_headers, global_trigger_repo.id, pr(number)).status_code == 400


def test_non_object_pr_entry_is_400(client, admin_headers, global_trigger_repo):
    r = client.post(f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests",
                    json={"pull_requests": [1, "x", None]}, headers=admin_headers)
    assert r.status_code == 400


def test_boundary_field_lengths_are_accepted(client, admin_headers, global_trigger_repo):
    r = post_prs(client, admin_headers, global_trigger_repo.id,
                 pr(1, title="t" * 256, raised_by="r" * 256, merge_commit_sha="a" * 40, base_branch="b" * 256))
    assert r.status_code == 201, r.json


def test_unknown_repo_is_404(client, admin_headers):
    assert post_prs(client, admin_headers, 9999, pr(1)).status_code == 404


def test_no_link_stores_pr_but_creates_no_triggers(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    assert post_prs(client, admin_headers, T, pr(1)).status_code == 201
    link_resp = link(client, admin_headers, project.id, T)
    assert link_resp.json["pr_count"] == 0
    g = client.get(f"/global/repositories/triggers/{T}/pull_requests", headers=admin_headers).json
    assert g["total"] == 1
