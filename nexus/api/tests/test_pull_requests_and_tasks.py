"""
Pull request ingest, fan-out to project links, the per-link trigger state, creating a task from a PR
(post_task rules) and the task status routes (ADRs 0008 and 0011).
"""
import json
from datetime import datetime, timedelta

import pytest

from app.helpers.base_model import db
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.task import Task

MERGED = "2030-01-01T10:00:00Z"
LATER = "2030-01-02T10:00:00Z"


# --------------------------------------------------------------------------- helpers


def pr(number=1, /, **fields) -> dict:
    """A valid PR body: merged on main, adding triggers/spec.json."""
    body = {
        "number": number, "title": f"PR {number}", "raised_by": "user1", "merged_at": MERGED,
        "merge_commit_sha": f"{number:040x}", "base_branch": "main", "files_truncated": False,
        "changed_files": [{"path": "triggers/spec.json", "status": "added"}],
    }
    body.update(fields)
    return body


def added(*paths) -> list:
    return [{"path": p, "status": "added"} for p in paths]


def post_prs(client, headers, repo_id, *prs):
    return client.post(f"/global/repositories/triggers/{repo_id}/pull_requests",
                       json={"pull_requests": list(prs)}, headers=headers)


def link(client, headers, pid, repo_id, **body):
    body.setdefault("watch_dir", "triggers")
    r = client.put(f"/projects/{pid}/repositories/triggers/{repo_id}", json=body, headers=headers)
    assert r.status_code in (200, 201), r.json()
    return r


def link_url(pid, repo_id):
    return f"/projects/{pid}/repositories/triggers/{repo_id}"


def trig_url(pid, repo_id, number=None):
    base = f"{link_url(pid, repo_id)}/pull_requests"
    return base if number is None else f"{base}/{number}"


def states(client, headers, pid, repo_id) -> dict:
    r = client.get(trig_url(pid, repo_id) + "?per_page=200", headers=headers)
    assert r.status_code == 200, r.json()
    return {i["number"]: i["state"] for i in r.json()["items"]}


def global_total(client, headers, repo_id) -> int:
    return client.get(f"/global/repositories/triggers/{repo_id}/pull_requests", headers=headers).json()["total"]


def set_enabled(project, enabled=True):
    project.enabled = enabled
    db.session.commit()


# --------------------------------------------------------------------------- ingest


def test_a_trigger_lists_its_spec_files(client, admin_headers, system_headers, project, global_trigger_repo):
    """Only added .json files under the link's watch_dir, the rule that decides the fan-out."""
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    files = added("triggers/a.json", "triggers/sub/b.json", "triggers/c.txt", "other/d.json", "triggers-old/e.json")
    files.append({"path": "triggers/f.json", "status": "modified"})
    post_prs(client, system_headers, T, pr(1, changed_files=files))

    t = client.get(trig_url(project.id, T, 1), headers=admin_headers).json()

    assert t["spec_files"] == ["triggers/a.json", "triggers/sub/b.json"]


def test_ingest_fans_out_and_is_idempotent(client, admin_headers, system_headers, project, global_trigger_repo):
    """Re-ingest never changes facts or state."""
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)

    assert post_prs(client, system_headers, T).json() == {"created": [], "existing": []}  # empty batch is fine
    assert post_prs(client, system_headers, T, pr(1, title="original"), pr(2)).json() == {"created": [1, 2], "existing": []}
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 2: "UNKNOWN"}

    client.patch(trig_url(project.id, T, 1), json={"state": "REJECTED", "state_cause": "bad"}, headers=system_headers)
    again = post_prs(client, system_headers, T, pr(1, title="changed", base_branch="dev"), pr(3))
    assert again.json() == {"created": [3], "existing": [1]}
    t = client.get(trig_url(project.id, T, 1), headers=admin_headers).json()
    assert (t["state"], t["state_cause"], t["title"]) == ("REJECTED", "bad", "original")
    assert (t["number"], t["raised_by"], t["project_id"], t["trigger_repository_id"]) == (1, "user1", project.id, T)
    assert t["merge_commit_sha"] == f"{1:040x}" and t["task_id"] is None

    # the same number twice in one batch: first wins
    dup = post_prs(client, system_headers, T, pr(4, title="first"), pr(4, title="second"))
    assert dup.json() == {"created": [4], "existing": [4]}
    assert client.get(trig_url(project.id, T, 4), headers=admin_headers).json()["title"] == "first"
    g = client.get(f"/global/repositories/triggers/{T}/pull_requests", headers=admin_headers).json()
    assert g["total"] == 4 and {"number", "title", "base_branch", "merged_at"} <= set(g["items"][0])


@pytest.mark.parametrize("count, status", [(100, 201), (101, 400)])
def test_batch_limit(client, admin_headers, system_headers, project, global_trigger_repo, count, status):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    r = post_prs(client, system_headers, T, *[pr(n) for n in range(1, count + 1)])
    assert r.status_code == status
    expected = count if status == 201 else 0  # a refused batch stores nothing
    assert global_total(client, admin_headers, T) == expected
    assert len(states(client, admin_headers, project.id, T)) == expected


def _bad(**fields):
    return {"pull_requests": [pr(1), pr(2, **fields)]}  # one bad PR refuses the whole batch


@pytest.mark.parametrize("body", [
    {"pull_requests": "x"},                                      # not a list
    {},                                                          # no pull_requests key
    {"pull_requests": [1, "x"]},                                 # entries must be objects
    {"pull_requests": [{k: v for k, v in pr(1).items() if k != "title"}]},   # missing required field
    _bad(bogus=1),                                               # extra field
    _bad(number="2"),                                            # wrong type
    _bad(number=0),                                              # numbers start at 1
    _bad(merged_at="yesterday"),                                 # unparsable date
    _bad(merge_commit_sha="a" * 41),                             # out of range
    _bad(changed_files=[{"path": "a.json"}]),                    # changed file needs a status
    _bad(files_truncated="false"),
], ids=lambda b: "-".join(str(k) for k in b) or "empty")
def test_invalid_ingest_bodies_are_400_and_store_nothing(client, admin_headers, system_headers, global_trigger_repo, body):
    T = global_trigger_repo.id
    r = client.post(f"/global/repositories/triggers/{T}/pull_requests", json=body, headers=system_headers)
    assert r.status_code == 400
    assert global_total(client, admin_headers, T) == 0


def test_merged_at_formats_and_utc_conversion(client, admin_headers, system_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    formats = ["2030-01-01T10:00:00", "2030-01-01T10:00:00.123456Z", "2030-01-01T10:00:00+00:00", "2030-01-01"]
    for n, merged_at in enumerate(formats, 1):
        assert post_prs(client, system_headers, T, pr(n, merged_at=merged_at)).status_code == 201
    r = post_prs(client, system_headers, T, pr(9, merged_at="2030-01-03T12:00:00+02:00"))
    assert r.status_code == 201
    items = client.get(f"/global/repositories/triggers/{T}/pull_requests?per_page=50", headers=admin_headers).json()["items"]
    assert [i for i in items if i["number"] == 9][0]["merged_at"].startswith("2030-01-03T10:00:00")


def test_disabled_and_unknown_repository_refuse_ingest(client, admin_headers, system_headers, global_trigger_repo):
    T = global_trigger_repo.id
    global_trigger_repo.enabled = False
    db.session.commit()
    r = post_prs(client, system_headers, T, pr(1))
    assert r.status_code == 400 and "disabled" in r.json()["error"]
    assert global_total(client, admin_headers, T) == 0
    assert post_prs(client, system_headers, 9999, pr(1)).status_code == 404


# --------------------------------------------------------------------------- cursor rule


def test_cursor_rule_link_first_then_ingest(client, admin_headers, system_headers, project, global_trigger_repo):
    """A link triggers only PRs after the latest stored PR (merged_at, ties by number); history is not replayed."""
    T = global_trigger_repo.id
    assert post_prs(client, system_headers, T, pr(5)).status_code == 201   # stored before any link: no trigger
    response = link(client, admin_headers, project.id, T)
    assert response.status_code == 201 and response.json()["pr_count"] == 0
    assert states(client, admin_headers, project.id, T) == {}

    post_prs(client, system_headers, T,
             pr(4),                                       # same merged_at as the cursor, lower number: out
             pr(6),                                       # same merged_at, higher number: in
             pr(7, merged_at="2029-12-31T10:00:00Z"))     # older than the cursor: out
    assert states(client, admin_headers, project.id, T) == {6: "UNKNOWN"}
    post_prs(client, system_headers, T, pr(8, merged_at=LATER))
    assert states(client, admin_headers, project.id, T) == {6: "UNKNOWN", 8: "UNKNOWN"}

    # a relink PUT neither replays nor moves the cursor
    before = client.get(link_url(project.id, T), headers=admin_headers).json()
    again = link(client, admin_headers, project.id, T)
    assert again.status_code == 200
    assert (again.json()["pr_count"], again.json()["pr_cursor"]) == (before["pr_count"], before["pr_cursor"]) == (2, LATER)


def test_cursor_with_nothing_stored_is_link_creation_time(client, admin_headers, system_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    post_prs(client, system_headers, T, pr(1, merged_at="2020-01-01T00:00:00Z"))
    assert states(client, admin_headers, project.id, T) == {}


def merged_hours_from_now(hours: int) -> str:
    return (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_unrevoke_skips_the_gap(client, admin_headers, system_headers, project, global_trigger_repo):
    """A PR merged while the link was revoked is stored but gets no trigger; one merged after the re-grant does."""
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    url = link_url(project.id, T)
    assert client.patch(url, json={"revoked": True}, headers=admin_headers).status_code == 200
    post_prs(client, system_headers, T, pr(2, merged_at=merged_hours_from_now(-1)))
    assert states(client, admin_headers, project.id, T) == {}

    restored = client.patch(url, json={"revoked": False}, headers=admin_headers)
    assert restored.status_code == 200 and restored.json()["active"] is True and restored.json()["pr_count"] == 0
    post_prs(client, system_headers, T, pr(3, merged_at=merged_hours_from_now(-1)), pr(4, merged_at=merged_hours_from_now(1)))
    assert global_total(client, admin_headers, T) == 3
    assert states(client, admin_headers, project.id, T) == {4: "UNKNOWN"}


def test_enabling_a_link_skips_the_gap(client, admin_headers, system_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T, enabled=False)
    post_prs(client, system_headers, T, pr(1, merged_at=merged_hours_from_now(-1)))
    assert states(client, admin_headers, project.id, T) == {}
    r = client.put(link_url(project.id, T), json={"watch_dir": "triggers"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["active"] is True
    assert states(client, admin_headers, project.id, T) == {}


def test_a_disabled_project_gets_no_trigger_and_enabling_it_skips_the_gap(
        client, admin_headers, system_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    # the cursor far back, so only the project being off keeps PR 1 from a trigger
    ProjectTriggerRepository.query.filter_by(project_id=project.id).one().initial_cursor = datetime(2000, 1, 1)
    db.session.commit()
    assert client.patch(f"/projects/{project.id}", json={"enabled": False}, headers=admin_headers).status_code == 200
    post_prs(client, system_headers, T, pr(1, merged_at=merged_hours_from_now(-1)))
    assert states(client, admin_headers, project.id, T) == {}  # stored, but a disabled project gets no trigger
    assert global_total(client, admin_headers, T) == 1

    assert client.patch(f"/projects/{project.id}", json={"enabled": True}, headers=admin_headers).status_code == 200
    assert states(client, admin_headers, project.id, T) == {}  # the gap is not replayed
    post_prs(client, system_headers, T, pr(2, merged_at=merged_hours_from_now(-1)), pr(3, merged_at=merged_hours_from_now(1)))
    assert states(client, admin_headers, project.id, T) == {3: "UNKNOWN"}


def test_a_revoked_project_gets_no_trigger_and_re_granting_it_skips_the_gap(
        client, admin_headers, system_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    # the cursor far back, so only the project being revoked keeps PR 1 from a trigger
    ProjectTriggerRepository.query.filter_by(project_id=project.id).one().initial_cursor = datetime(2000, 1, 1)
    db.session.commit()
    revoked = client.patch(f"/projects/{project.id}", json={"revoked": True}, headers=admin_headers)
    assert revoked.status_code == 200 and revoked.json()["enabled"] is True
    post_prs(client, system_headers, T, pr(1, merged_at=merged_hours_from_now(-1)))
    assert states(client, admin_headers, project.id, T) == {}  # stored, but a revoked project gets no trigger
    assert global_total(client, admin_headers, T) == 1

    assert client.patch(f"/projects/{project.id}", json={"revoked": False}, headers=admin_headers).status_code == 200
    assert states(client, admin_headers, project.id, T) == {}  # the gap is not replayed
    post_prs(client, system_headers, T, pr(2, merged_at=merged_hours_from_now(-1)), pr(3, merged_at=merged_hours_from_now(1)))
    assert states(client, admin_headers, project.id, T) == {3: "UNKNOWN"}


def disabled_project_with_a_stored_pull_request(client, admin_headers, system_headers, project, T):
    """The project linked to T, then disabled, then PR 1 stored while it is off: it has no trigger."""
    link(client, admin_headers, project.id, T)
    assert client.patch(f"/projects/{project.id}", json={"enabled": False}, headers=admin_headers).status_code == 200
    post_prs(client, system_headers, T, pr(1, merged_at=merged_hours_from_now(1)))
    assert states(client, admin_headers, project.id, T) == {}
    assert global_total(client, admin_headers, T) == 1


def test_enabling_with_backfill_creates_the_triggers_stored_while_it_was_off(
        client, admin_headers, system_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    disabled_project_with_a_stored_pull_request(client, admin_headers, system_headers, project, T)
    post_prs(client, system_headers, T, pr(2, merged_at=merged_hours_from_now(2)))

    on = client.patch(f"/projects/{project.id}", json={"enabled": True, "backfill": True}, headers=admin_headers)

    assert on.status_code == 200 and on.json()["enabled"] is True and "backfill" not in on.json()
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 2: "UNKNOWN"}
    # the cursor did not move: a PR merged after enabling is still in scope
    post_prs(client, system_headers, T, pr(3, merged_at=merged_hours_from_now(3)))
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 2: "UNKNOWN", 3: "UNKNOWN"}


def test_enabling_with_backfill_false_or_without_it_skips_the_gap(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    disabled_project_with_a_stored_pull_request(client, admin_headers, system_headers, project, T)

    on = client.patch(f"/projects/{project.id}", json={"enabled": True, "backfill": False}, headers=admin_headers)

    assert on.status_code == 200 and on.json()["enabled"] is True
    assert states(client, admin_headers, project.id, T) == {}


def test_enabling_with_backfill_twice_creates_no_duplicates(client, admin_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    disabled_project_with_a_stored_pull_request(client, admin_headers, system_headers, project, T)
    patch_project = lambda **body: client.patch(f"/projects/{project.id}", json=body, headers=admin_headers)

    assert patch_project(enabled=True, backfill=True).status_code == 200
    assert patch_project(enabled=False).status_code == 200
    assert patch_project(enabled=True, backfill=True).status_code == 200  # a second time, the trigger exists

    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}
    link_row = ProjectTriggerRepository.query.filter_by(project_id=project.id).one()
    assert len(link_row.pull_request_triggers) == 1


def test_backfill_leaves_a_link_that_is_off_without_triggers(client, admin_headers, system_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T, enabled=False)
    client.patch(f"/projects/{project.id}", json={"enabled": False}, headers=admin_headers)
    post_prs(client, system_headers, T, pr(1, merged_at=merged_hours_from_now(1)))

    assert client.patch(f"/projects/{project.id}", json={"enabled": True, "backfill": True},
                        headers=admin_headers).status_code == 200

    assert states(client, admin_headers, project.id, T) == {}


def test_a_deleted_project_gets_no_trigger(client, admin_headers, system_headers, project, other_project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    link(client, admin_headers, other_project.id, T)
    assert client.delete(f"/projects/{project.id}", headers=admin_headers).status_code == 204
    post_prs(client, system_headers, T, pr(1, merged_at=merged_hours_from_now(1)))
    assert states(client, admin_headers, other_project.id, T) == {1: "UNKNOWN"}
    assert ProjectTriggerRepository.query.filter_by(trigger_repository_id=T).count() == 1


# --------------------------------------------------------------------------- matching: no trigger unless it matches


@pytest.mark.parametrize("watch_dir, changed_files, matches", [
    ("triggers", added("triggers/nested/deep/spec.json"), True),
    ("triggers", added("triggers-old/spec.json"), False),             # a sibling with the same prefix is not inside
    ("triggers", added("triggers/readme.md"), False),                 # only .json files
    ("triggers", [{"path": f"triggers/{s}.json", "status": s} for s in ("removed", "modified", "renamed")], False),
    ("triggers", [{"path": "triggers/old.json", "status": "removed"}, *added("docs/a.md", "triggers/new.json")], True),
    ("triggers", [], False),
    ("triggers/a", added("triggers/ab/spec.json"), False),
    ("/triggers/", added("triggers/spec.json"), True),               # slashes are normalised
    ("", added("root.json"), True),                                  # empty watch_dir is the repository root
])
def test_file_matching_against_watch_dir(client, admin_headers, system_headers, project, global_trigger_repo, watch_dir,
                                         changed_files, matches):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T, watch_dir=watch_dir)
    assert post_prs(client, system_headers, T, pr(1, changed_files=changed_files)).status_code == 201
    assert states(client, admin_headers, project.id, T) == ({1: "UNKNOWN"} if matches else {})


def test_truncated_file_list_matches_but_base_branch_still_applies(client, admin_headers, system_headers, project,
                                                                   global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    truncated = dict(files_truncated=True, changed_files=added("unrelated/file.txt"))
    post_prs(client, system_headers, T, pr(1, **truncated), pr(2, base_branch="dev", **truncated))
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}


def test_base_branch_default_override_and_case(client, admin_headers, system_headers, project, other_project, global_trigger_repo):
    T = global_trigger_repo.id
    assert link(client, admin_headers, project.id, T).json()["base_branch"] == "main"
    link(client, admin_headers, other_project.id, T, base_branch="release/1.0")
    post_prs(client, system_headers, T, pr(1), pr(2, base_branch="Main"), pr(3, base_branch="release/1.0"),
             pr(4, base_branch="master"))
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}
    assert states(client, admin_headers, other_project.id, T) == {3: "UNKNOWN"}


def test_two_projects_on_one_repo_are_independent(client, admin_headers, system_headers, project, other_project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    post_prs(client, system_headers, T, pr(1))
    link(client, admin_headers, other_project.id, T, watch_dir="other")  # its cursor is after PR 1
    post_prs(client, system_headers, T, pr(2, merged_at=LATER, changed_files=added("other/x.json")),
             pr(3, merged_at=LATER, changed_files=added("triggers/y.json")))
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 3: "UNKNOWN"}
    assert states(client, admin_headers, other_project.id, T) == {2: "UNKNOWN"}
    assert global_total(client, admin_headers, T) == 3  # one PR row, a trigger per matching link

    # a state change and a revoke in one project do not touch the other
    client.patch(trig_url(project.id, T, 1), json={"state": "REJECTED", "state_cause": "x"}, headers=system_headers)
    client.patch(link_url(project.id, T), json={"revoked": True}, headers=admin_headers)
    post_prs(client, system_headers, T, pr(4, merged_at="2030-02-01T00:00:00Z", changed_files=added("other/z.json")))
    assert states(client, admin_headers, other_project.id, T) == {2: "UNKNOWN", 4: "UNKNOWN"}
    assert states(client, admin_headers, project.id, T) == {1: "REJECTED", 3: "UNKNOWN"}
    assert client.get(trig_url(other_project.id, T, 1), headers=admin_headers).status_code == 404


# --------------------------------------------------------------------------- trigger list and state


def test_list_filter_pagination_and_unknown(client, admin_headers, system_headers, project, global_trigger_repo, pr_trigger,
                                            ingest_prs):
    T = global_trigger_repo.id
    list_url = trig_url(project.id, T)
    ingest_prs(T, 2)
    ingest_prs(T, 3, base_branch="dev")  # non-matching: no trigger
    assert client.patch(f"{list_url}/2", json={"state": "REJECTED", "state_cause": "bad"},
                        headers=system_headers).status_code == 200

    rejected = client.get(f"{list_url}?state=REJECTED", headers=admin_headers)
    assert rejected.json()["total"] == 1 and rejected.json()["items"][0]["number"] == 2
    for bad in ("IGNORED", "NOPE"):
        assert client.get(f"{list_url}?state={bad}", headers=admin_headers).status_code == 400

    page = client.get(f"{list_url}?per_page=1&page=2", headers=admin_headers)
    assert page.status_code == 200 and page.json()["total"] == 2 and len(page.json()["items"]) == 1
    past = client.get(f"{list_url}?page=9&per_page=1", headers=admin_headers)
    assert past.status_code == 200 and past.json()["items"] == []

    assert client.get(f"{list_url}/99", headers=admin_headers).status_code == 404
    assert client.get(pr_trigger, headers=admin_headers).json()["state"] == "UNKNOWN"


def test_patch_state_legal_transitions_and_cause(client, system_headers, pr_trigger):
    for body, state, cause in [
        ({"state": "REJECTED", "state_cause": "bad spec"}, "REJECTED", "bad spec"),
        ({"state_cause": "new"}, "REJECTED", "new"),   # cause alone updates a REJECTED trigger
    ]:
        r = client.patch(pr_trigger, json=body, headers=system_headers)
        assert r.status_code == 200, (body, r.json())
        assert r.json()["state"] == state and r.json()["state_cause"] == cause


def test_patch_state_unknown_to_yielded_is_final(client, system_headers, pr_trigger):
    assert client.patch(pr_trigger, json={"state": "YIELDED"}, headers=system_headers).json()["state"] == "YIELDED"
    assert client.patch(pr_trigger, json={"state": "UNKNOWN"}, headers=system_headers).status_code == 409


@pytest.mark.parametrize("body", [
    {"state": "IGNORED", "state_cause": "not ours"},   # IGNORED is not a stored state
    {"state": "REJECTED"},                             # REJECTED needs a cause
    {"state": "UNKNOWN", "state_cause": "no cause allowed"},
    {"state": "BOGUS"},
    {"state_cause": "why"},                            # a cause alone is only valid on a REJECTED trigger
])
def test_patch_state_illegal_bodies_are_400_and_change_nothing(client, admin_headers, system_headers, pr_trigger, body):
    assert client.patch(pr_trigger, json=body, headers=system_headers).status_code == 400
    assert client.get(pr_trigger, headers=admin_headers).json()["state"] == "UNKNOWN"


def test_trigger_of_other_project_is_404(client, system_headers, other_project, global_trigger_repo, pr_trigger):
    url = trig_url(other_project.id, global_trigger_repo.id, 1)
    assert client.patch(url, json={"state": "UNKNOWN"}, headers=system_headers).status_code == 404


# --------------------------------------------------------------------------- post_task


def spec(**fields) -> str:
    return json.dumps({"spec": {"image": "i:1", **fields}})


def post_task(client, headers, pr_url, raw):
    return client.post(f"{pr_url}/task", json={"spec_raw": raw}, headers=headers)


def create_task(client, headers, pr_url, raw) -> dict:
    r = post_task(client, headers, pr_url, raw)
    assert r.status_code == 201, r.json()
    return r.json()


def pr_state(client, admin_headers, pr_url) -> dict:
    return client.get(pr_url, headers=admin_headers).json()


def test_create_task_yields_pr_and_is_idempotent(client, admin_headers, system_headers, project, pr_trigger, spec_raw):
    task = create_task(client, system_headers, pr_trigger, spec_raw)
    assert (task["status"], task["name"], task["project_id"]) == ("PENDING", "PR 1", project.id)
    assert task["spec"]["image"] == "img:1" and task["spec"]["dataset_id"] is None
    pr_row = pr_state(client, admin_headers, pr_trigger)
    assert (pr_row["state"], pr_row["task_id"], pr_row["state_cause"]) == ("YIELDED", task["id"], None)

    # an existing task is returned (200) whatever the second body is
    for body in ({"spec_raw": spec(image="other:2")}, {}):
        again = client.post(f"{pr_trigger}/task", json=body, headers=system_headers)
        assert again.status_code == 200 and again.json()["id"] == task["id"] and again.json()["spec"]["image"] == "img:1"
    assert client.get(f"/projects/{project.id}/tasks", headers=admin_headers).json()["total"] == 1


def test_a_revoked_project_creates_no_task(client, admin_headers, system_headers, project, pr_trigger, spec_raw):
    project.revoked = True
    db.session.commit()
    refused = post_task(client, system_headers, pr_trigger, spec_raw)
    assert refused.status_code == 409 and refused.json()["error"] == f"Project {project.id} is revoked"
    assert Task.query.count() == 0
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "UNKNOWN"  # untouched, so a re-grant can yield it

    project.revoked = False
    db.session.commit()
    assert post_task(client, system_headers, pr_trigger, spec_raw).status_code == 201


def test_spec_options_are_kept(client, system_headers, pr_trigger):
    task = create_task(client, system_headers, pr_trigger,
                       json.dumps({"note": "ignored", "spec": {"docker_image": "img:9", "name": "MyTask",
                                                               "env": {"MY_VAR": "x"}, "params": {"p": {"q": [1]}}}}))
    assert task["name"] == "MyTask" and task["spec"]["image"] == "img:9"  # docker_image is an alias of image
    assert task["spec"]["env"] == {"MY_VAR": "x"}
    assert Task.query.get(task["id"]).params == {"p": {"q": [1]}}


def test_dataset_default_and_case_insensitive_override(client, admin_headers, system_headers, project, global_trigger_repo,
                                                       linked_dataset, global_dataset, make_global_dataset,
                                                       pr_trigger, spec_raw):
    second = make_global_dataset(name="Second")
    assert client.put(f"/projects/{project.id}/datasets/{second.id}", json={}, headers=admin_headers).status_code == 201
    assert create_task(client, system_headers, pr_trigger, spec_raw)["spec"]["dataset_id"] == global_dataset.id

    assert post_prs(client, system_headers, global_trigger_repo.id, pr(2)).status_code == 201
    other_pr = trig_url(project.id, global_trigger_repo.id, 2)
    named = create_task(client, system_headers, other_pr, spec(dataset="SECOND"))
    assert named["spec"]["dataset_id"] == second.id


@pytest.mark.parametrize("problem", ["unknown_name", "unlinked", "globally_disabled", "revoked_link"])
def test_unusable_dataset_rejects_the_pr(client, admin_headers, system_headers, project, linked_dataset, global_dataset,
                                         make_global_dataset, pr_trigger, spec_raw, problem):
    raw = spec_raw
    if problem == "unknown_name":
        raw = spec(dataset="does-not-exist")
    elif problem == "unlinked":
        make_global_dataset(name="elsewhere")  # exists globally, never linked to the project
        raw = spec(dataset="elsewhere")
    elif problem == "globally_disabled":
        global_dataset.enabled = False
        db.session.commit()
    else:
        client.patch(f"/projects/{project.id}/datasets/{global_dataset.id}", json={"revoked": True},
                     headers=admin_headers)
    assert post_task(client, system_headers, pr_trigger, raw).status_code == 400
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "REJECTED"


@pytest.mark.parametrize("raw", [
    "{}",                                           # no spec key
    spec(image=5),                                  # wrong type
    spec(bogus=1),                                  # unknown spec field
    spec(env="notdict"),
    "not json at all",
    '{"spec": "a string"}',
    json.dumps({"spec": {"image": "i:1", "params": {"blob": "x" * (70 * 1024)}}}),   # over the size limit
])
def test_bad_spec_rejects_the_pr(client, admin_headers, system_headers, pr_trigger, raw):
    r = post_task(client, system_headers, pr_trigger, raw)
    assert r.status_code in (400, 413) and "error" in r.json()
    row = pr_state(client, admin_headers, pr_trigger)
    assert row["state"] == "REJECTED" and row["task_id"] is None and row["state_cause"]


@pytest.mark.parametrize("body", [{}, {"spec_raw": 5}])
def test_spec_raw_must_be_a_string_and_the_pr_is_not_judged(client, admin_headers, system_headers, pr_trigger, body):
    assert client.post(f"{pr_trigger}/task", json=body, headers=system_headers).status_code == 400
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "UNKNOWN"


@pytest.mark.parametrize("setup", ["rejected", "revoked", "disabled"])
def test_only_unknown_triggers_of_an_active_link_get_a_task(client, admin_headers, system_headers, project, global_trigger_repo,
                                                            pr_trigger, spec_raw, setup):
    url = link_url(project.id, global_trigger_repo.id)
    if setup == "rejected":
        client.patch(pr_trigger, json={"state": "REJECTED", "state_cause": "bad"}, headers=system_headers)
    elif setup == "revoked":
        client.patch(url, json={"revoked": True}, headers=admin_headers)
    else:
        client.patch(url, json={"enabled": False}, headers=admin_headers)
    assert post_task(client, system_headers, pr_trigger, spec_raw).status_code == 409
    assert pr_state(client, admin_headers, pr_trigger)["task_id"] is None


def test_post_task_404s_and_disabled_project(client, system_headers, project, other_project, global_trigger_repo,
                                           pr_trigger, spec_raw):
    base = link_url(project.id, global_trigger_repo.id)
    assert post_task(client, system_headers, f"{base}/pull_requests/99", spec_raw).status_code == 404
    other = f"{link_url(other_project.id, global_trigger_repo.id)}/pull_requests/1"
    assert post_task(client, system_headers, other, spec_raw).status_code == 404


def test_a_disabled_project_gets_no_task_from_a_pr_until_enabled(client, admin_headers, system_headers, project, pr_trigger, spec_raw):
    set_enabled(project, False)
    assert post_task(client, system_headers, pr_trigger, spec_raw).status_code == 409
    row = pr_state(client, admin_headers, pr_trigger)
    assert row["state"] == "UNKNOWN" and row["task_id"] is None
    set_enabled(project, True)
    assert post_task(client, system_headers, pr_trigger, spec_raw).status_code == 201


def test_a_revoked_project_gets_no_task_from_a_pr_until_regranted(client, admin_headers, system_headers, project, pr_trigger, spec_raw):
    project.revoked = True
    db.session.commit()
    assert post_task(client, system_headers, pr_trigger, spec_raw).status_code == 409
    row = pr_state(client, admin_headers, pr_trigger)
    assert row["state"] == "UNKNOWN" and row["task_id"] is None
    project.revoked = False
    db.session.commit()
    assert post_task(client, system_headers, pr_trigger, spec_raw).status_code == 201


# --------------------------------------------------------------------------- task status and listing


@pytest.fixture
def tid(client, system_headers, pr_trigger, spec_raw) -> int:
    return create_task(client, system_headers, pr_trigger, spec_raw)["id"]


def patch_task(client, headers, project, task_id, body):
    return client.patch(f"/projects/{project.id}/tasks/{task_id}", json=body, headers=headers)


def test_task_status_lifecycle_fields_and_get(client, admin_headers, system_headers, project, tid):
    one = client.get(f"/projects/{project.id}/tasks/{tid}", headers=admin_headers)
    assert {"id", "name", "status", "spec", "project_id"} <= set(one.json())
    for status in ("QUEUED", "RUNNING"):
        assert patch_task(client, system_headers, project, tid, {"status": status}).json()["status"] == status
    r = patch_task(client, system_headers, project, tid, {"status": "FAILED", "executor_run_id": "run-1", "exit_code": 137,
                                                "state_cause": "oom"})
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["executor_run_id"], r.json()["exit_code"], r.json()["state_cause"]) \
        == ("FAILED", "run-1", 137, "oom")
    assert client.get(f"/projects/{project.id}/tasks/999999", headers=admin_headers).status_code == 404
    assert patch_task(client, system_headers, project, 999, {"status": "RUNNING"}).status_code == 404
    assert client.get(f"/projects/{project.id}/tasks/{tid}/results", headers=admin_headers).json() == []


@pytest.mark.parametrize("terminal", ["SUCCESS", "CANCELED"])
def test_finished_tasks_cannot_change_status(client, admin_headers, system_headers, project, tid, terminal):
    assert patch_task(client, system_headers, project, tid, {"status": terminal}).status_code == 200
    assert patch_task(client, system_headers, project, tid, {"status": "RUNNING"}).status_code == 409
    assert client.get(f"/projects/{project.id}/tasks/{tid}", headers=admin_headers).json()["status"] == terminal
    same = patch_task(client, system_headers, project, tid, {"status": terminal})  # the same status again is fine
    assert same.status_code == 200 and same.json()["status"] == terminal


@pytest.mark.parametrize("body", [
    {"status": "bogus"}, {"status": None},             # not a TaskStatus
    {"status": "RUNNING", "bogus": 1},                 # unknown field applies nothing
    {"name": "x"},                                     # immutable
    {"executor_run_id": 42},                            # wrong type
    {},
])
def test_bad_task_patches_are_400_and_change_nothing(client, admin_headers, system_headers, project, tid, body):
    assert patch_task(client, system_headers, project, tid, body).status_code == 400
    assert client.get(f"/projects/{project.id}/tasks/{tid}", headers=admin_headers).json()["status"] == "PENDING"


def test_retry_resets_a_failed_task_only(client, admin_headers, system_headers, project, tid):
    assert client.post(f"/projects/{project.id}/tasks/{tid}/retry", json={}, headers=admin_headers).status_code == 400  # not failed yet
    patch_task(client, system_headers, project, tid, {"status": "FAILED", "executor_run_id": "r", "exit_code": 1})
    retry = client.post(f"/projects/{project.id}/tasks/{tid}/retry", json={}, headers=admin_headers)
    assert retry.status_code == 200 and retry.json()["status"] == "PENDING"
    assert retry.json()["executor_run_id"] is None and retry.json()["exit_code"] is None


def test_task_results_list_the_delivery(client, admin_headers, system_headers, project, linked_results_repo, global_results_repo,
                                        make_task):
    task = make_task()
    assert patch_task(client, system_headers, project, task.id, {"status": "SUCCESS"}).status_code == 200
    posted = client.post(f"/projects/{project.id}/results",
                         json={"task_id": task.id, "results_repository_id": global_results_repo.id},
                         headers=system_headers)
    assert posted.status_code == 201
    results = client.get(f"/projects/{project.id}/tasks/{task.id}/results", headers=admin_headers)
    assert [r["id"] for r in results.json()] == [posted.json()["id"]]
    assert client.get(f"/projects/{project.id}/tasks/999/results", headers=admin_headers).status_code == 404


def test_tasks_list_filters_and_pagination(client, admin_headers, project, other_project, make_task):
    ids = [make_task(status="RUNNING").id, make_task(status="RUNNING").id, make_task(status="FAILED").id,
           make_task().id]
    other = make_task(project=other_project, status="RUNNING")
    tasks = lambda q="": client.get(f"/projects/{project.id}/tasks{q}", headers=admin_headers)  # noqa: E731

    assert tasks().json()["total"] == 4
    assert {t["status"] for t in tasks("?status=RUNNING").json()["tasks"]} == {"RUNNING"}
    assert other.id not in [t["id"] for t in tasks().json()["tasks"]]
    others = client.get(f"/projects/{other_project.id}/tasks?status=RUNNING", headers=admin_headers)
    assert [t["id"] for t in others.json()["tasks"]] == [other.id]
    assert tasks("?status=SUCCESS").json()["total"] == 0
    assert tasks("?status=bogus").status_code == 400

    first = tasks("?page=1&per_page=2").json()
    assert [t["id"] for t in first["tasks"]] == ids[:2]
    assert (first["total"], first["pages"], first["page"], first["per_page"]) == (4, 2, 1, 2)
    assert tasks("?page=9&per_page=2").json()["tasks"] == []  # past the end is an empty page
    for clamped in ("page=0", "per_page=-1"):  # below one is clamped
        assert tasks(f"?{clamped}").status_code == 200
    assert 400 <= tasks("?page=abc").status_code < 500


def test_a_task_of_another_project_is_a_404(client, admin_headers, system_headers, other_project, make_task):
    task = make_task()
    url = f"/projects/{other_project.id}/tasks/{task.id}"
    assert client.get(url, headers=admin_headers).status_code == 404
    assert client.get(f"{url}/results", headers=admin_headers).status_code == 404
    assert client.patch(url, json={"status": "RUNNING"}, headers=system_headers).status_code == 404
    assert client.post(f"{url}/retry", json={}, headers=admin_headers).status_code == 404
    assert client.get("/projects/99999/tasks", headers=admin_headers).status_code == 404


def test_task_trigger_is_the_pull_request_with_its_repository(client, admin_headers, system_headers, project, other_project,
                                                              global_trigger_repo, pr_trigger, spec_raw):
    task = create_task(client, system_headers, pr_trigger, spec_raw)
    url = f"/projects/{project.id}/tasks/{task['id']}/trigger"
    response = client.get(url, headers=admin_headers)
    assert response.status_code == 200, response.json()
    assert response.json() == {
        **client.get(pr_trigger, headers=admin_headers).json(),
        "trigger_repository": {
            "id": global_trigger_repo.id, "repo_path": global_trigger_repo.repo_path, "uri": global_trigger_repo.uri,
        },
    }
    assert response.json()["number"] == 1 and response.json()["merge_commit_sha"]
    assert client.get(f"/projects/{other_project.id}/tasks/{task['id']}/trigger", headers=admin_headers).status_code == 404


def test_task_trigger_of_a_task_made_by_hand_is_a_404(client, admin_headers, project, make_task):
    task = make_task()
    assert client.get(f"/projects/{project.id}/tasks/{task.id}/trigger", headers=admin_headers).status_code == 404


def test_rejected_trigger_cannot_go_back_to_unknown(client, admin_headers, system_headers, pr_trigger):
    client.patch(pr_trigger, json={"state": "REJECTED", "state_cause": "bad"}, headers=system_headers)
    assert client.patch(pr_trigger, json={"state": "UNKNOWN"}, headers=system_headers).status_code == 409
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "REJECTED"


# --------------------------------------------------------------------------- gaps from the ADR audit


@pytest.mark.parametrize("status", ["RUNNING", "SUCCESS", "FAILED"])
def test_patching_a_pr_task_status_leaves_the_trigger_yielded(client, admin_headers, system_headers, project, pr_trigger, tid, status):
    """The trigger state is the pull request's own (ADR 0001); the task's status does not move it."""
    assert pr_state(client, admin_headers, pr_trigger)["state"] == "YIELDED"
    assert patch_task(client, system_headers, project, tid, {"status": status}).status_code == 200
    trigger = pr_state(client, admin_headers, pr_trigger)
    assert trigger["state"] == "YIELDED" and trigger["task_id"] == tid


def test_cancel_is_not_implemented_and_leaves_the_task_alone(client, admin_headers, project, tid):
    response = client.post(f"/projects/{project.id}/tasks/{tid}/cancel", json={}, headers=admin_headers)
    assert response.status_code == 501
    assert client.get(f"/projects/{project.id}/tasks/{tid}", headers=admin_headers).json()["status"] == "PENDING"


def test_one_merge_commit_on_two_base_branches_is_stored_twice_and_fans_out_to_each(
    client, admin_headers, project, other_project, global_trigger_repo
):
    """A fast-forward or rebase merge gives a release branch and main the same commit under two numbers."""
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T, base_branch="main")
    link(client, admin_headers, other_project.id, T, base_branch="release")
    sha = f"{9:040x}"

    response = post_prs(
        client, admin_headers, T,
        pr(1, merge_commit_sha=sha, base_branch="main"), pr(2, merge_commit_sha=sha, base_branch="release"),
    )

    assert response.status_code == 201
    assert response.json() == {"created": [1, 2], "existing": []}
    assert global_total(client, admin_headers, T) == 2
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}
    assert states(client, admin_headers, other_project.id, T) == {2: "UNKNOWN"}


def test_a_repeated_merge_commit_on_the_same_base_branch_under_a_new_number_is_skipped(
    client, admin_headers, system_headers, project, global_trigger_repo, caplog
):
    """The duplicate stores nothing and gets no trigger, the rest of the batch is stored, and the post is a 201."""
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    assert post_prs(client, system_headers, T, pr(1)).status_code == 201

    with caplog.at_level("WARNING", logger="pull_request_fanout"):
        response = post_prs(client, system_headers, T, pr(2), pr(5, merge_commit_sha=f"{1:040x}"), pr(6))

    assert response.status_code == 201
    assert response.json() == {"created": [2, 6], "existing": [1]}
    assert global_total(client, admin_headers, T) == 3
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN", 2: "UNKNOWN", 6: "UNKNOWN"}
    assert "#5" in caplog.text and "#1" in caplog.text
    # Ingest is not blocked: a later batch is stored
    assert post_prs(client, system_headers, T, pr(7)).json() == {"created": [7], "existing": []}


def test_posting_the_same_pull_request_again_changes_nothing(client, admin_headers, system_headers, project, global_trigger_repo):
    T = global_trigger_repo.id
    link(client, admin_headers, project.id, T)
    assert post_prs(client, system_headers, T, pr(1)).status_code == 201

    again = post_prs(client, system_headers, T, pr(1))

    assert again.status_code == 201
    assert again.json() == {"created": [], "existing": [1]}
    assert global_total(client, admin_headers, T) == 1
    assert states(client, admin_headers, project.id, T) == {1: "UNKNOWN"}
