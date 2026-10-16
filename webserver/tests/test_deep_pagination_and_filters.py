"""Deep tests of pagination, response shape, ordering and query filters of the list endpoints."""
import pytest

from app.helpers.base_model import db
from app.models.project import Project

TASK_STATUSES = ["PENDING", "QUEUED", "RUNNING", "SUCCESS", "FAILED", "CANCELED"]


def make_projects(count, prefix="P", **fields):
    projects = []
    for i in range(count):
        p = Project(name=f"{prefix}{i:02d}")
        for k, v in fields.items():
            setattr(p, k, v)
        p.add()
        projects.append(p)
    return projects


def ids(items):
    return [i["id"] for i in items]


# ---------------------------------------------------------------- projects (parse_query_params)

def test_projects_default_page_shape(client, admin_headers):
    make_projects(3)
    r = client.get("/projects", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["page"] == 1
    assert r.json["per_page"] == 25
    assert r.json["total"] == 3
    assert r.json["pages"] == 1
    assert len(r.json["items"]) == 3


def test_projects_empty_list_shape(client, admin_headers):
    r = client.get("/projects", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["items"] == []
    assert r.json["total"] == 0


def test_projects_per_page_splits_pages(client, admin_headers):
    make_projects(5)
    r = client.get("/projects?per_page=2", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["total"] == 5
    assert r.json["pages"] == 3
    assert len(r.json["items"]) == 2
    last = client.get("/projects?per_page=2&page=3", headers=admin_headers)
    assert last.status_code == 200
    assert len(last.json["items"]) == 1
    assert last.json["page"] == 3


def test_projects_pages_are_disjoint_and_complete(client, admin_headers):
    created = make_projects(5)
    seen = []
    for page in (1, 2, 3):
        r = client.get(f"/projects?per_page=2&page={page}", headers=admin_headers)
        assert r.status_code == 200
        seen += ids(r.json["items"])
    assert sorted(seen) == sorted(p.id for p in created)
    assert len(seen) == len(set(seen))


def test_projects_ordering_is_stable_across_requests(client, admin_headers):
    make_projects(6)
    first = [ids(client.get("/projects?per_page=3&page=1", headers=admin_headers).json["items"]),
             ids(client.get("/projects?per_page=3&page=2", headers=admin_headers).json["items"])]
    again = [ids(client.get("/projects?per_page=3&page=1", headers=admin_headers).json["items"]),
             ids(client.get("/projects?per_page=3&page=2", headers=admin_headers).json["items"])]
    assert first == again
    flat = first[0] + first[1]
    assert flat == sorted(flat)


def test_projects_page_past_the_end_is_empty_200(client, admin_headers):
    make_projects(2)
    r = client.get("/projects?page=9", headers=admin_headers)
    assert r.status_code == 200, r.json
    assert r.json["items"] == []
    assert r.json["total"] == 2


@pytest.mark.parametrize("query", ["page=abc", "per_page=xyz", "page=1.5", "per_page=", "page=--1"])
def test_projects_non_numeric_pagination_is_400(client, admin_headers, query):
    r = client.get(f"/projects?{query}", headers=admin_headers)
    assert r.status_code == 400
    assert "error" in r.json


@pytest.mark.parametrize("query", ["page=0", "page=-1", "per_page=0", "per_page=-5"])
def test_projects_zero_or_negative_pagination_is_400_or_clamped(client, admin_headers, query):
    make_projects(3)
    r = client.get(f"/projects?{query}", headers=admin_headers)
    # Sensible: 400, or clamped to a valid page. Never a 404 or 500.
    assert r.status_code in (200, 400), r.status_code
    if r.status_code == 200:
        assert r.json["page"] >= 1
        assert r.json["per_page"] >= 1


def test_projects_filter_enabled_true(client, admin_headers):
    make_projects(2, prefix="off")
    on = make_projects(3, prefix="on", enabled=True)
    r = client.get("/projects?enabled=true", headers=admin_headers)
    assert r.status_code == 200
    assert sorted(ids(r.json["items"])) == sorted(p.id for p in on)
    assert r.json["total"] == 3


def test_projects_filter_enabled_false(client, admin_headers):
    off = make_projects(2, prefix="off")
    make_projects(3, prefix="on", enabled=True)
    r = client.get("/projects?enabled=false", headers=admin_headers)
    assert r.status_code == 200
    assert sorted(ids(r.json["items"])) == sorted(p.id for p in off)


def test_projects_filter_locked(client, admin_headers):
    make_projects(2, prefix="u")
    locked = make_projects(1, prefix="l", locked=True)
    r = client.get("/projects?locked=true", headers=admin_headers)
    assert r.status_code == 200
    assert ids(r.json["items"]) == [locked[0].id]


def test_projects_combined_filters_are_anded(client, admin_headers):
    make_projects(1, prefix="a", enabled=True)
    make_projects(1, prefix="b", locked=True)
    both = make_projects(1, prefix="c", enabled=True, locked=True)
    r = client.get("/projects?enabled=true&locked=true", headers=admin_headers)
    assert r.status_code == 200
    assert ids(r.json["items"]) == [both[0].id]


def test_projects_filter_name_and_comparison_suffixes(client, admin_headers):
    ps = make_projects(4)
    r = client.get(f"/projects?name={ps[1].name}", headers=admin_headers)
    assert ids(r.json["items"]) == [ps[1].id]
    r = client.get(f"/projects?id__gt={ps[1].id}", headers=admin_headers)
    assert sorted(ids(r.json["items"])) == [ps[2].id, ps[3].id]
    r = client.get(f"/projects?id__lte={ps[1].id}", headers=admin_headers)
    assert sorted(ids(r.json["items"])) == [ps[0].id, ps[1].id]
    r = client.get(f"/projects?id__ne={ps[0].id}", headers=admin_headers)
    assert r.json["total"] == 3


def test_projects_filter_no_match_is_empty_200(client, admin_headers):
    make_projects(2)
    r = client.get("/projects?name=nothing-like-this", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["items"] == []
    assert r.json["total"] == 0


def test_projects_filter_unknown_field_is_400(client, admin_headers):
    make_projects(1)
    r = client.get("/projects?bogus=1", headers=admin_headers)
    assert r.status_code == 400
    assert "bogus" in r.json["error"]


def test_projects_filter_applies_before_pagination(client, admin_headers):
    make_projects(4, prefix="off")
    make_projects(3, prefix="on", enabled=True)
    r = client.get("/projects?enabled=true&per_page=2&page=2", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["total"] == 3
    assert r.json["pages"] == 2
    assert len(r.json["items"]) == 1


def test_projects_item_keys(client, admin_headers, project):
    r = client.get("/projects", headers=admin_headers)
    item = r.json["items"][0]
    for key in ("id", "name", "enabled", "locked", "default_dataset_id"):
        assert key in item


# ---------------------------------------------------------------- other parse_query_params lists

def test_datasets_list_pagination_shape(client, admin_headers, make_global_dataset, global_secret):
    for name in ("a", "b", "c"):
        make_global_dataset(name=name)
    r = client.get("/global/datasets?per_page=2", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["total"] == 3
    assert r.json["pages"] == 2
    assert r.json["per_page"] == 2
    assert len(r.json["items"]) == 2


def test_datasets_non_numeric_page_is_400(client, admin_headers):
    r = client.get("/global/datasets?page=x", headers=admin_headers)
    assert r.status_code == 400


def test_datasets_page_past_the_end_is_empty_200(client, admin_headers, global_dataset):
    r = client.get("/global/datasets?page=5", headers=admin_headers)
    assert r.status_code == 200, r.json
    assert r.json["items"] == []


def test_audit_list_shape_and_bad_page(client, admin_headers):
    r = client.get("/audit", headers=admin_headers)
    assert r.status_code == 200
    for key in ("items", "page", "per_page", "total", "pages"):
        assert key in r.json
    assert client.get("/audit?per_page=nope", headers=admin_headers).status_code == 400


# ---------------------------------------------------------------- tasks

def make_tasks(make_task, count, **fields):
    return [make_task(**fields) for _ in range(count)]


def test_tasks_default_shape(client, admin_headers, make_task):
    make_tasks(make_task, 3)
    r = client.get("/tasks", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["total"] == 3
    assert r.json["page"] == 1
    assert r.json["per_page"] == 10
    assert r.json["pages"] == 1
    assert len(r.json["tasks"]) == 3


def test_tasks_default_per_page_is_10(client, admin_headers, make_task):
    make_tasks(make_task, 12)
    r = client.get("/tasks", headers=admin_headers)
    assert len(r.json["tasks"]) == 10
    assert r.json["total"] == 12
    assert r.json["pages"] == 2
    r2 = client.get("/tasks?page=2", headers=admin_headers)
    assert len(r2.json["tasks"]) == 2


def test_tasks_ordered_by_id_across_pages(client, admin_headers, make_task):
    created = make_tasks(make_task, 5)
    got = []
    for page in (1, 2, 3):
        r = client.get(f"/tasks?per_page=2&page={page}", headers=admin_headers)
        assert r.status_code == 200
        got += ids(r.json["tasks"])
    assert got == [t.id for t in created]


def test_tasks_empty_list(client, admin_headers):
    r = client.get("/tasks", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["tasks"] == []
    assert r.json["total"] == 0
    assert r.json["pages"] == 0


@pytest.mark.parametrize("query", ["page=abc", "per_page=abc", "page=1.2", "project_id=abc"])
def test_tasks_non_numeric_params_are_400(client, admin_headers, query):
    r = client.get(f"/tasks?{query}", headers=admin_headers)
    assert r.status_code == 400
    assert "error" in r.json


def test_tasks_page_past_the_end_is_empty_200(client, admin_headers, make_task):
    make_tasks(make_task, 2)
    r = client.get("/tasks?page=7", headers=admin_headers)
    assert r.status_code == 200, r.status_code
    assert r.json["tasks"] == []
    assert r.json["total"] == 2


@pytest.mark.parametrize("query", ["page=0", "page=-1", "per_page=0", "per_page=-3"])
def test_tasks_zero_or_negative_pagination(client, admin_headers, make_task, query):
    make_tasks(make_task, 2)
    r = client.get(f"/tasks?{query}", headers=admin_headers)
    assert r.status_code in (200, 400), r.status_code


def test_tasks_filter_by_each_status(client, admin_headers, make_task):
    made = {s: make_task(status=s) for s in TASK_STATUSES}
    for status, task in made.items():
        r = client.get(f"/tasks?status={status}", headers=admin_headers)
        assert r.status_code == 200
        assert ids(r.json["tasks"]) == [task.id]
        assert r.json["total"] == 1


def test_tasks_invalid_status_is_400(client, admin_headers, make_task):
    make_task()
    for bad in ("NOPE", "pending", ""):
        r = client.get(f"/tasks?status={bad}", headers=admin_headers)
        assert r.status_code == 400, bad


def test_tasks_filter_status_total_and_pages(client, admin_headers, make_task):
    make_tasks(make_task, 3, status="FAILED")
    make_tasks(make_task, 2, status="SUCCESS")
    r = client.get("/tasks?status=FAILED&per_page=2", headers=admin_headers)
    assert r.json["total"] == 3
    assert r.json["pages"] == 2
    assert all(t["status"] == "FAILED" for t in r.json["tasks"])


def test_tasks_filter_by_project_id(client, admin_headers, make_task, project, other_project):
    mine = make_tasks(make_task, 2)
    theirs = [make_task(project=other_project)]
    r = client.get(f"/tasks?project_id={project.id}", headers=admin_headers)
    assert ids(r.json["tasks"]) == [t.id for t in mine]
    r = client.get(f"/tasks?project_id={other_project.id}", headers=admin_headers)
    assert ids(r.json["tasks"]) == [t.id for t in theirs]


def test_tasks_filter_unknown_project_is_empty(client, admin_headers, make_task):
    make_task()
    r = client.get("/tasks?project_id=9999", headers=admin_headers)
    assert r.status_code == 200
    assert r.json["tasks"] == []
    assert r.json["total"] == 0


def test_tasks_filters_combine(client, admin_headers, make_task, project, other_project):
    make_task(status="FAILED")
    wanted = make_task(project=other_project, status="FAILED")
    make_task(project=other_project, status="SUCCESS")
    r = client.get(f"/tasks?project_id={other_project.id}&status=FAILED", headers=admin_headers)
    assert ids(r.json["tasks"]) == [wanted.id]


# ---------------------------------------------------------------- trigger repositories (global)

def test_trigger_repos_list_is_a_plain_ordered_array(client, admin_headers, make_trigger_repo):
    repos = [make_trigger_repo(uri=f"github.com/org/r{i}") for i in range(3)]
    r = client.get("/global/repositories/triggers", headers=admin_headers)
    assert r.status_code == 200
    assert ids(r.json) == [x.id for x in repos]


def test_trigger_repos_active_link_requires_enabled_project(
        client, admin_headers, linked_trigger_repo, project, global_trigger_repo):
    # project fixture is disabled -> link is not active
    r = client.get("/global/repositories/triggers?active_link=true", headers=admin_headers)
    assert r.status_code == 200
    assert r.json == []
    full = client.get("/global/repositories/triggers", headers=admin_headers)
    assert ids(full.json) == [global_trigger_repo.id]


def test_trigger_repos_active_link_value_is_case_insensitive(
        client, admin_headers, enabled_project, linked_trigger_repo, global_trigger_repo):
    for value in ("true", "TRUE", "True"):
        r = client.get(f"/global/repositories/triggers?active_link={value}", headers=admin_headers)
        assert ids(r.json) == [global_trigger_repo.id], value


def test_trigger_repos_active_link_false_returns_everything(
        client, admin_headers, enabled_project, linked_trigger_repo, make_trigger_repo, global_trigger_repo):
    other = make_trigger_repo(uri="github.com/org/unlinked")
    r = client.get("/global/repositories/triggers?active_link=false", headers=admin_headers)
    assert ids(r.json) == [global_trigger_repo.id, other.id]


def test_trigger_repos_active_link_excludes_disabled_repo(
        client, admin_headers, enabled_project, linked_trigger_repo, global_trigger_repo):
    global_trigger_repo.enabled = False
    db.session.commit()
    r = client.get("/global/repositories/triggers?active_link=true", headers=admin_headers)
    assert r.json == []


def test_trigger_repos_active_link_excludes_disabled_link(
        client, admin_headers, enabled_project, linked_trigger_repo, global_trigger_repo, lock_project):
    p = client.patch(
        f"/projects/{enabled_project.id}/repositories/triggers/{global_trigger_repo.id}",
        json={"enabled": False}, headers=admin_headers)
    assert p.status_code == 200, p.json
    r = client.get("/global/repositories/triggers?active_link=true", headers=admin_headers)
    assert r.json == []


def test_trigger_repos_active_link_lists_repo_once_with_two_projects(
        client, admin_headers, enabled_project, other_project, linked_trigger_repo, global_trigger_repo):
    other_project.enabled = True
    db.session.commit()
    put = client.put(f"/projects/{other_project.id}/repositories/triggers/{global_trigger_repo.id}",
                     json={"watch_dir": "x"}, headers=admin_headers)
    assert put.status_code == 201
    r = client.get("/global/repositories/triggers?active_link=true", headers=admin_headers)
    assert ids(r.json) == [global_trigger_repo.id]


# ---------------------------------------------------------------- pull request lists

def pr_list(client, admin_headers, pid, tid, query=""):
    return client.get(f"/projects/{pid}/repositories/triggers/{tid}/pull_requests{query}", headers=admin_headers)


def test_project_pr_list_shape_and_defaults(client, admin_headers, project, linked_trigger_repo,
                                             global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2, 3)
    r = pr_list(client, admin_headers, project.id, global_trigger_repo.id)
    assert r.status_code == 200
    assert r.json["page"] == 1
    assert r.json["per_page"] == 20
    assert r.json["total"] == 3
    assert len(r.json["items"]) == 3


def test_project_pr_list_sorted_by_merge_time_desc(client, admin_headers, project, linked_trigger_repo,
                                                    global_trigger_repo, make_pr_batch):
    body = make_pr_batch(1)
    for number, merged in ((1, "2030-01-01T10:00:00Z"), (2, "2030-03-01T10:00:00Z"), (3, "2030-02-01T10:00:00Z")):
        body["pull_requests"] += make_pr_batch(number, merged_at=merged)["pull_requests"]
    body["pull_requests"] = body["pull_requests"][1:]
    r = client.post(f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests",
                    json=body, headers=admin_headers)
    assert r.status_code == 201, r.json
    listed = pr_list(client, admin_headers, project.id, global_trigger_repo.id)
    assert [i["number"] for i in listed.json["items"]] == [2, 3, 1]


def test_project_pr_list_ties_broken_by_number_desc(client, admin_headers, project, linked_trigger_repo,
                                                     global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2, 3, 4)  # same merged_at
    first = pr_list(client, admin_headers, project.id, global_trigger_repo.id)
    assert [i["number"] for i in first.json["items"]] == [4, 3, 2, 1]
    again = pr_list(client, admin_headers, project.id, global_trigger_repo.id)
    assert again.json == first.json


def test_project_pr_list_pagination_walks_all(client, admin_headers, project, linked_trigger_repo,
                                               global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2, 3, 4, 5)
    seen = []
    for page in (1, 2, 3):
        r = pr_list(client, admin_headers, project.id, global_trigger_repo.id, f"?per_page=2&page={page}")
        assert r.status_code == 200
        assert r.json["total"] == 5
        seen += [i["number"] for i in r.json["items"]]
    assert seen == [5, 4, 3, 2, 1]


def test_project_pr_list_past_the_end_is_empty_200(client, admin_headers, project, linked_trigger_repo,
                                                    global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1)
    r = pr_list(client, admin_headers, project.id, global_trigger_repo.id, "?page=50")
    assert r.status_code == 200
    assert r.json["items"] == []
    assert r.json["total"] == 1


@pytest.mark.parametrize("query", ["?page=x", "?per_page=y", "?page=2.5"])
def test_project_pr_list_non_numeric_is_400(client, admin_headers, project, linked_trigger_repo,
                                            global_trigger_repo, query):
    r = pr_list(client, admin_headers, project.id, global_trigger_repo.id, query)
    assert r.status_code == 400


@pytest.mark.parametrize("query", ["?page=0", "?page=-1", "?per_page=0", "?per_page=-1"])
def test_project_pr_list_zero_or_negative_pagination(client, admin_headers, project, linked_trigger_repo,
                                                      global_trigger_repo, ingest_prs, query):
    ingest_prs(global_trigger_repo.id, 1, 2)
    r = pr_list(client, admin_headers, project.id, global_trigger_repo.id, query)
    assert r.status_code == 400 or (r.status_code == 200 and r.json["page"] >= 1 and r.json["per_page"] >= 1)


def test_project_pr_list_state_filter_all_values(client, admin_headers, project, linked_trigger_repo,
                                                  global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2)
    ingest_prs(global_trigger_repo.id, 3, base_branch="dev")
    unknown = pr_list(client, admin_headers, project.id, global_trigger_repo.id, "?state=UNKNOWN")
    assert sorted(i["number"] for i in unknown.json["items"]) == [1, 2]
    ignored = pr_list(client, admin_headers, project.id, global_trigger_repo.id, "?state=IGNORED")
    assert [i["number"] for i in ignored.json["items"]] == [3]
    for state in ("REJECTED", "YIELDED"):
        r = pr_list(client, admin_headers, project.id, global_trigger_repo.id, f"?state={state}")
        assert r.status_code == 200
        assert r.json["items"] == []
        assert r.json["total"] == 0


def test_project_pr_list_state_filter_reflects_patch(client, admin_headers, project, pr_trigger):
    p = client.patch(pr_trigger, json={"state": "REJECTED", "state_cause": "bad"}, headers=admin_headers)
    assert p.status_code == 200
    listing = pr_trigger.rsplit("/", 1)[0]
    assert client.get(listing + "?state=REJECTED", headers=admin_headers).json["total"] == 1
    assert client.get(listing + "?state=UNKNOWN", headers=admin_headers).json["total"] == 0


@pytest.mark.parametrize("bad", ["NOPE", "unknown", ""])
def test_project_pr_list_invalid_state_is_400(client, admin_headers, project, linked_trigger_repo,
                                              global_trigger_repo, bad):
    r = pr_list(client, admin_headers, project.id, global_trigger_repo.id, f"?state={bad}")
    assert r.status_code == 400


def test_project_pr_list_state_with_pagination_totals(client, admin_headers, project, linked_trigger_repo,
                                                       global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2, 3)
    ingest_prs(global_trigger_repo.id, 4, 5, base_branch="dev")
    r = pr_list(client, admin_headers, project.id, global_trigger_repo.id, "?state=UNKNOWN&per_page=2&page=2")
    assert r.json["total"] == 3
    assert len(r.json["items"]) == 1


def test_project_pr_list_is_scoped_to_the_link(client, admin_headers, project, other_project,
                                                linked_trigger_repo, global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1)
    r = pr_list(client, admin_headers, other_project.id, global_trigger_repo.id)
    assert r.status_code == 404


def test_project_pr_list_unknown_repo_404(client, admin_headers, project):
    assert pr_list(client, admin_headers, project.id, 999).status_code == 404


def test_global_pr_list_shape_order_and_paging(client, admin_headers, global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2, 3)
    base = f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests"
    r = client.get(base, headers=admin_headers)
    assert r.status_code == 200
    assert (r.json["page"], r.json["per_page"], r.json["total"]) == (1, 20, 3)
    assert [i["number"] for i in r.json["items"]] == [3, 2, 1]
    p2 = client.get(base + "?per_page=2&page=2", headers=admin_headers)
    assert [i["number"] for i in p2.json["items"]] == [1]
    assert client.get(base + "?page=9", headers=admin_headers).json["items"] == []


def test_global_pr_list_bad_params(client, admin_headers, global_trigger_repo):
    base = f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests"
    assert client.get(base + "?page=abc", headers=admin_headers).status_code == 400
    assert client.get("/global/repositories/triggers/999/pull_requests", headers=admin_headers).status_code == 404


def test_global_pr_list_has_pages(client, admin_headers, global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2, 3)
    base = f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests"
    r = client.get(base + "?per_page=2", headers=admin_headers)
    assert r.json["pages"] == 2


# ---------------------------------------------------------------- results ?step=

def make_result_at(client, admin_headers, project, make_task, repo_id, step=None):
    task = make_task()
    r = client.post(f"/projects/{project.id}/results",
                    json={"task_id": task.id, "results_repository_id": repo_id}, headers=admin_headers)
    assert r.status_code == 201, r.json
    rid = r.json["id"]
    if step:
        body = {"step": step}
        if step in ("OPENED", "MERGED", "CLOSED"):
            body.update({"number": 5, "url": "https://x/pull/5"})
        p = client.patch(f"/projects/{project.id}/results/{rid}", json=body, headers=admin_headers)
        assert p.status_code == 200, p.json
    return rid


def test_results_step_filter_repeated_and_ordered(client, admin_headers, project, linked_results_repo,
                                                   global_results_repo, make_task):
    a = make_result_at(client, admin_headers, project, make_task, global_results_repo.id, "PUSHED")
    b = make_result_at(client, admin_headers, project, make_task, global_results_repo.id, "OPENED")
    c = make_result_at(client, admin_headers, project, make_task, global_results_repo.id)
    url = f"/projects/{project.id}/results"
    both = client.get(url + "?step=PUSHED&step=OPENED", headers=admin_headers)
    assert both.status_code == 200
    assert ids(both.json) == [a, b]
    assert ids(client.get(url + "?step=UNKNOWN", headers=admin_headers).json) == [c]
    assert ids(client.get(url, headers=admin_headers).json) == [a, b, c]
    assert client.get(url + "?step=MERGED", headers=admin_headers).json == []


def test_results_step_one_bad_value_rejects_all(client, admin_headers, project, linked_results_repo):
    url = f"/projects/{project.id}/results"
    assert client.get(url + "?step=OPENED&step=NOPE", headers=admin_headers).status_code == 400
    assert client.get(url + "?step=opened", headers=admin_headers).status_code == 400


def test_results_list_scoped_to_project(client, admin_headers, project, other_project, linked_results_repo,
                                         global_results_repo, make_task):
    make_result_at(client, admin_headers, project, make_task, global_results_repo.id)
    r = client.get(f"/projects/{other_project.id}/results", headers=admin_headers)
    assert r.status_code == 200
    assert r.json == []
    assert client.get("/projects/999/results", headers=admin_headers).status_code == 404


# ---------------------------------------------------------------- other lists

def test_secrets_and_results_repos_lists_are_ordered_arrays(client, admin_headers, make_global_secret,
                                                             make_results_repo, global_secret):
    make_global_secret(label="second")
    labels = [s["label"] for s in client.get("/global/secrets", headers=admin_headers).json]
    assert labels == ["test-creds", "second"]
    repos = [make_results_repo(uri=f"github.com/org/res{i}") for i in range(3)]
    r = client.get("/global/repositories/results", headers=admin_headers)
    assert r.status_code == 200
    assert ids(r.json) == [x.id for x in repos]


def test_project_trigger_links_list_ordered_and_unfiltered(client, admin_headers, project, make_trigger_repo):
    repos = [make_trigger_repo(uri=f"github.com/org/l{i}") for i in range(3)]
    for repo in repos:
        assert client.put(f"/projects/{project.id}/repositories/triggers/{repo.id}",
                          json={"watch_dir": "t"}, headers=admin_headers).status_code == 201
    r = client.get(f"/projects/{project.id}/repositories/triggers", headers=admin_headers)
    assert r.status_code == 200
    assert [i["trigger_repository"]["id"] for i in r.json] == [x.id for x in repos]
    assert client.get("/projects/999/repositories/triggers", headers=admin_headers).status_code == 404
