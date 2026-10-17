"""Pagination shape, ordering and query filters of the list endpoints."""
import pytest

from app.helpers.base_model import db
from app.models.project import Project

TASK_STATUSES = ["PENDING", "QUEUED", "RUNNING", "SUCCESS", "FAILED", "CANCELED"]


def make_projects(count, prefix="P", **fields):
    projects = []
    for i in range(count):
        project = Project(name=f"{prefix}{i:02d}")
        for key, value in fields.items():
            setattr(project, key, value)
        project.add()
        projects.append(project)
    return projects


def ids(items):
    return [i["id"] for i in items]


def get(client, admin_headers, url):
    return client.get(url, headers=admin_headers)


def pr_list_url(project, repo, query=""):
    return f"/projects/{project.id}/repositories/triggers/{repo.id}/pull_requests{query}"


# ---------------------------------------------------------------- pagination edge cases, per list kind

@pytest.fixture(params=["projects", "datasets", "tasks", "pull_requests"])
def paged(request, client):
    """(url, items key) of a list holding two items, for each representative paginated list."""
    kind = request.param
    if kind == "projects":
        make_projects(2)
        return "/projects", "items"
    if kind == "datasets":
        for name in ("a", "b"):
            request.getfixturevalue("make_global_dataset")(name=name)
        return "/global/datasets", "items"
    if kind == "tasks":
        make_task = request.getfixturevalue("make_task")
        make_task(), make_task()
        return f"/projects/{request.getfixturevalue('project').id}/tasks", "tasks"
    request.getfixturevalue("linked_trigger_repo")
    repo = request.getfixturevalue("global_trigger_repo")
    request.getfixturevalue("ingest_prs")(repo.id, 1, 2)
    return pr_list_url(request.getfixturevalue("project"), repo), "items"


def test_page_past_the_end_is_empty_200(client, admin_headers, paged):
    url, key = paged
    response = get(client, admin_headers, f"{url}?page=50")
    assert response.status_code == 200, response.json
    assert response.json[key] == [] and response.json["total"] == 2


def test_page_or_per_page_below_one_is_clamped(client, admin_headers, paged):
    url, _ = paged
    for query in ("page=0", "page=-1", "per_page=0", "per_page=-5"):
        response = get(client, admin_headers, f"{url}?{query}")
        assert response.status_code == 200, query
        assert response.json["page"] >= 1 and response.json["per_page"] >= 1


def test_non_numeric_page_params_are_400(client, admin_headers, paged):
    url, _ = paged
    for query in ("page=abc", "per_page=xyz", "page=1.5"):
        response = get(client, admin_headers, f"{url}?{query}")
        assert response.status_code == 400 and "error" in response.json, query


# ---------------------------------------------------------------- projects

def test_projects_default_shape_and_walk(client, admin_headers):
    assert get(client, admin_headers, "/projects").json["items"] == []
    created = make_projects(5)
    first = get(client, admin_headers, "/projects").json
    assert (first["page"], first["per_page"], first["total"], first["pages"]) == (1, 25, 5, 1)
    assert {"id", "name", "enabled", "locked", "default_dataset_id"} <= set(first["items"][0])
    seen = []
    for page in (1, 2, 3):
        response = get(client, admin_headers, f"/projects?per_page=2&page={page}").json
        assert response["total"] == 5 and response["pages"] == 3 and response["page"] == page
        seen += ids(response["items"])
    assert seen == sorted(p.id for p in created)  # stable id order, disjoint and complete
    assert get(client, admin_headers, "/projects/").status_code == 200  # trailing slash


def test_projects_filters(client, admin_headers):
    make_projects(2, prefix="off", locked=False)
    enabled = make_projects(2, prefix="on", enabled=True, locked=False)
    both = make_projects(1, prefix="both", enabled=True, locked=True)
    locked_only = make_projects(1, prefix="lock", locked=True)

    def listed(query):
        response = get(client, admin_headers, f"/projects?{query}")
        assert response.status_code == 200, response.json
        return sorted(ids(response.json["items"]))

    assert listed("enabled=true") == sorted(ids_of(enabled + both))
    assert len(listed("enabled=false")) == 3
    assert listed(f"id__lte={enabled[0].id}") == [p.id for p in Project.query.order_by(Project.id) if p.id <= enabled[0].id]
    assert listed("locked=true") == sorted(ids_of(both + locked_only))
    assert listed("enabled=true&locked=true") == ids_of(both)  # filters are ANDed
    assert listed(f"name={enabled[0].name}") == [enabled[0].id]
    assert listed(f"id__gt={both[0].id}") == [locked_only[0].id]
    assert listed(f"name__ne={enabled[0].name}") != listed("")
    assert listed("name=nothing-like-this") == []
    page = get(client, admin_headers, "/projects?enabled=true&per_page=2&page=2").json
    assert page["total"] == 3 and page["pages"] == 2 and len(page["items"]) == 1  # filter before pagination
    bad = get(client, admin_headers, "/projects?bogus=1")
    assert bad.status_code == 400 and "bogus" in bad.json["error"]


def ids_of(projects):
    return [p.id for p in projects]


# ---------------------------------------------------------------- datasets

def test_datasets_list_shape(client, admin_headers, make_global_dataset, global_secret):
    for name in ("a", "b", "c"):
        make_global_dataset(name=name)
    response = get(client, admin_headers, "/global/datasets?per_page=2").json
    assert (response["total"], response["pages"], response["per_page"], len(response["items"])) == (3, 2, 2, 2)


# ---------------------------------------------------------------- tasks

def test_tasks_pages_and_ordering(client, admin_headers, make_task, project):
    tasks_url = f"/projects/{project.id}/tasks"
    empty = get(client, admin_headers, tasks_url).json
    assert empty["tasks"] == [] and empty["total"] == 0 and empty["pages"] == 0
    created = [make_task() for _ in range(12)]
    first = get(client, admin_headers, tasks_url).json
    assert (first["page"], first["per_page"], first["total"], first["pages"]) == (1, 10, 12, 2)
    second = get(client, admin_headers, f"{tasks_url}?page=2").json
    assert ids(first["tasks"]) + ids(second["tasks"]) == [t.id for t in created]  # ordered by id


def test_tasks_filters(client, admin_headers, make_task, project, other_project):
    tasks_url = f"/projects/{project.id}/tasks"
    by_status = {status: make_task(status=status) for status in TASK_STATUSES}
    for status, task in by_status.items():
        response = get(client, admin_headers, f"{tasks_url}?status={status}")
        assert response.status_code == 200 and ids(response.json["tasks"]) == [task.id]
    theirs = make_task(project=other_project, status="FAILED")
    mine = get(client, admin_headers, tasks_url).json
    assert theirs.id not in ids(mine["tasks"]) and mine["total"] == len(TASK_STATUSES)
    both = get(client, admin_headers, f"/projects/{other_project.id}/tasks?status=FAILED").json
    assert ids(both["tasks"]) == [theirs.id]
    paged_by_status = get(client, admin_headers, f"{tasks_url}?status=FAILED&per_page=1").json
    assert paged_by_status["total"] == 1 and paged_by_status["pages"] == 1
    for bad in ("status=NOPE", "status=pending", "status="):
        assert get(client, admin_headers, f"{tasks_url}?{bad}").status_code == 400, bad


# ---------------------------------------------------------------- trigger repositories and pull requests

def test_global_repo_lists_are_ordered_arrays(client, admin_headers, make_trigger_repo, make_results_repo,
                                              make_global_secret, global_secret):
    make_global_secret(label="second")
    assert [s["label"] for s in get(client, admin_headers, "/global/secrets").json] == ["test-creds", "second"]
    triggers = [make_trigger_repo(uri=f"github.com/org/t{i}") for i in range(3)]
    results = [make_results_repo(uri=f"github.com/org/r{i}") for i in range(3)]
    assert ids(get(client, admin_headers, "/global/repositories/triggers").json) == [r.id for r in triggers]
    assert ids(get(client, admin_headers, "/global/repositories/results").json) == [r.id for r in results]


def test_trigger_repos_active_link_filter(client, admin_headers, project, other_project, linked_trigger_repo,
                                          global_trigger_repo, make_trigger_repo):
    url = "/global/repositories/triggers"
    unlinked = make_trigger_repo(uri="github.com/org/unlinked")
    # the project is disabled, so its link is not active; false/absent return everything
    assert get(client, admin_headers, url + "?active_link=true").json == []
    assert ids(get(client, admin_headers, url + "?active_link=false").json) == [global_trigger_repo.id, unlinked.id]
    project.enabled = other_project.enabled = True
    db.session.commit()
    link = client.put(f"/projects/{other_project.id}/repositories/triggers/{global_trigger_repo.id}",
                      json={"watch_dir": "x"}, headers=admin_headers)
    assert link.status_code == 201
    for value in ("true", "TRUE", "True"):  # case-insensitive, and listed once despite two projects
        assert ids(get(client, admin_headers, f"{url}?active_link={value}").json) == [global_trigger_repo.id]
    global_trigger_repo.enabled = False  # a disabled repo is never active
    db.session.commit()
    assert get(client, admin_headers, url + "?active_link=true").json == []


def test_project_trigger_link_list_is_ordered_and_404_for_unknown_project(
        client, admin_headers, project, make_trigger_repo):
    repos = [make_trigger_repo(uri=f"github.com/org/l{i}") for i in range(3)]
    for repo in repos:
        put = client.put(f"/projects/{project.id}/repositories/triggers/{repo.id}",
                         json={"watch_dir": "t"}, headers=admin_headers)
        assert put.status_code == 201
    listed = get(client, admin_headers, f"/projects/{project.id}/repositories/triggers").json
    assert [i["trigger_repository"]["id"] for i in listed] == [r.id for r in repos]
    assert get(client, admin_headers, "/projects/999/repositories/triggers").status_code == 404


def test_pr_list_shape_order_and_paging(client, admin_headers, project, linked_trigger_repo, global_trigger_repo,
                                        ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2, 3, 4, 5)  # same merged_at: ties broken by number desc
    response = get(client, admin_headers, pr_list_url(project, global_trigger_repo)).json
    assert (response["page"], response["per_page"], response["total"]) == (1, 20, 5)
    assert [i["number"] for i in response["items"]] == [5, 4, 3, 2, 1]
    seen = []
    for page in (1, 2, 3):
        part = get(client, admin_headers, pr_list_url(project, global_trigger_repo, f"?per_page=2&page={page}")).json
        assert part["pages"] == 3
        seen += [i["number"] for i in part["items"]]
    assert seen == [5, 4, 3, 2, 1]
    glob = get(client, admin_headers, f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests?per_page=2")
    assert glob.json["pages"] == 3 and [i["number"] for i in glob.json["items"]] == [5, 4]


def test_pr_list_sorted_by_merge_time_desc(client, admin_headers, project, linked_trigger_repo, global_trigger_repo,
                                           make_pr_batch):
    body = make_pr_batch(1)
    body["pull_requests"] = []
    for number, merged in ((1, "2030-01-01T10:00:00Z"), (2, "2030-03-01T10:00:00Z"), (3, "2030-02-01T10:00:00Z")):
        body["pull_requests"] += make_pr_batch(number, merged_at=merged)["pull_requests"]
    posted = client.post(f"/global/repositories/triggers/{global_trigger_repo.id}/pull_requests",
                         json=body, headers=admin_headers)
    assert posted.status_code == 201, posted.json
    listed = get(client, admin_headers, pr_list_url(project, global_trigger_repo))
    assert [i["number"] for i in listed.json["items"]] == [2, 3, 1]


def test_pr_list_state_filter(client, admin_headers, project, linked_trigger_repo, global_trigger_repo, ingest_prs):
    ingest_prs(global_trigger_repo.id, 1, 2, 3)
    ingest_prs(global_trigger_repo.id, 4, base_branch="dev")  # non-matching PR creates no project trigger

    def state(value, extra=""):
        return get(client, admin_headers, pr_list_url(project, global_trigger_repo, f"?state={value}{extra}"))

    unknown = state("UNKNOWN", "&per_page=2&page=2")
    assert unknown.json["total"] == 3 and len(unknown.json["items"]) == 1
    for empty in ("REJECTED", "YIELDED"):
        assert state(empty).json["total"] == 0
    for bad in ("IGNORED", "NOPE", "unknown", ""):
        assert state(bad).status_code == 400, bad


def test_pr_list_state_reflects_patch_and_is_scoped_to_link(client, admin_headers, project, other_project, pr_trigger,
                                                            global_trigger_repo):
    patched = client.patch(pr_trigger, json={"state": "REJECTED", "state_cause": "bad"}, headers=admin_headers)
    assert patched.status_code == 200
    listing = pr_trigger.rsplit("/", 1)[0]
    assert get(client, admin_headers, listing + "?state=REJECTED").json["total"] == 1
    assert get(client, admin_headers, listing + "?state=UNKNOWN").json["total"] == 0
    assert get(client, admin_headers, pr_list_url(other_project, global_trigger_repo)).status_code == 404
    assert get(client, admin_headers, f"/projects/{project.id}/repositories/triggers/999/pull_requests").status_code == 404
    assert get(client, admin_headers, "/global/repositories/triggers/999/pull_requests").status_code == 404


# ---------------------------------------------------------------- results ?step=

def make_result(client, admin_headers, project, make_task, repo_id, step=None):
    task = make_task(status="SUCCESS")
    created = client.post(f"/projects/{project.id}/results",
                          json={"task_id": task.id, "results_repository_id": repo_id}, headers=admin_headers)
    assert created.status_code == 201, created.json
    if step:
        body = {"step": step}
        if step == "OPENED":
            body.update({"number": 5, "url": "https://x/pull/5"})
        patched = client.patch(f"/projects/{project.id}/results/{created.json['id']}", json=body, headers=admin_headers)
        assert patched.status_code == 200, patched.json
    return created.json["id"]


def test_results_step_filter(client, admin_headers, project, other_project, linked_results_repo, global_results_repo,
                             make_task):
    pushed = make_result(client, admin_headers, project, make_task, global_results_repo.id, "PUSHED")
    opened = make_result(client, admin_headers, project, make_task, global_results_repo.id, "OPENED")
    fresh = make_result(client, admin_headers, project, make_task, global_results_repo.id)
    url = f"/projects/{project.id}/results"
    assert ids(get(client, admin_headers, url).json) == [pushed, opened, fresh]
    assert ids(get(client, admin_headers, url + "?step=PUSHED&step=OPENED").json) == [pushed, opened]  # repeatable
    assert ids(get(client, admin_headers, url + "?step=UNKNOWN").json) == [fresh]
    assert get(client, admin_headers, url + "?step=MERGED").json == []
    for bad in ("step=OPENED&step=NOPE", "step=opened"):  # one bad value rejects the whole request
        assert get(client, admin_headers, f"{url}?{bad}").status_code == 400
    assert get(client, admin_headers, f"/projects/{other_project.id}/results").json == []  # scoped to the project
    assert get(client, admin_headers, "/projects/999/results").status_code == 404
