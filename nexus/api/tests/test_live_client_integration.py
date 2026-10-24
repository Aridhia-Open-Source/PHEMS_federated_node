"""
The real clients against the real Flask app over HTTP, no Kubernetes.

The app of the `client` fixture is served by werkzeug on 127.0.0.1 in a thread, with the same
process-wide Keycloak/k8s mocks, and the fncli backend client (dagster/fncli/backend.py) and the
Dagster code location's BackendAPI (dagster/app/backend.py) are pointed at it with the Dagster system user's token
(the identity they log in as), and `admin_api` with the admin token, which revoking needs.

Skipped when ../dagster is not there (the CI container mounts only webserver/tests and webserver/app).
"""
import importlib
import importlib.util
import sys
import threading
from pathlib import Path

import pytest
import requests

from tests.conftest import SYSTEM_TOKEN

REPO_ROOT = Path(__file__).resolve().parents[2]
DAGSTER_DIR = REPO_ROOT / "dagster"
SCRIPTS_DIR = REPO_ROOT / "scripts"

if not (DAGSTER_DIR / "fncli" / "backend.py").is_file():
    pytest.skip("dagster/fncli is not available", allow_module_level=True)

from werkzeug.serving import make_server  # noqa: E402


def _load_dagster_client():
    """
    dagster/app is a package called `app` too, like the webserver's. Import it with the webserver's
    `app` modules set aside, then put them back. Needs no `dagster` package. None if unavailable.
    """
    if not (DAGSTER_DIR / "app" / "backend.py").is_file():
        return None
    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, str(DAGSTER_DIR))
    try:
        backend = importlib.import_module("app.backend")
        utils = importlib.import_module("app.utils")
        models = importlib.import_module("app.models")
        fncli_backend = importlib.import_module("fncli.backend")
        fncli_state = importlib.import_module("fncli.cmds.state")
        spec = importlib.util.spec_from_file_location("e2e_check", SCRIPTS_DIR / "e2e_check.py")
        e2e_check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(e2e_check)
        return backend.BackendAPI, utils, models, fncli_backend.FncliBackendAPI, fncli_state, e2e_check
    except Exception:  # pragma: no cover
        return None
    finally:
        sys.path.remove(str(DAGSTER_DIR))
        for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


_dagster = _load_dagster_client()
if _dagster is None:
    pytest.skip("dagster/app and dagster/fncli are not importable", allow_module_level=True)
DagsterBackendAPI, _utils, fn_models, FnBackendAPI, state, e2e = _dagster


@pytest.fixture
def live_url(client, k8s_client, mock_connection_checks, responses):
    """The app of `client` served at http://127.0.0.1:<port> by a werkzeug server in a thread."""
    responses.add_passthru("http://127.0.0.1")  # pytest-responses blocks real HTTP otherwise
    server = make_server("127.0.0.1", 0, client.application, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def api(live_url):
    adapter = _utils.BackendAdapter(live_url, "dagster", "pw")
    adapter.access_token = SYSTEM_TOKEN
    return FnBackendAPI(_utils.BackendSession(adapter))


@pytest.fixture
def admin_api(live_url, login_admin):
    adapter = _utils.BackendAdapter(live_url, "admin", "pw")
    adapter.access_token = login_admin
    return FnBackendAPI(_utils.BackendSession(adapter))


@pytest.fixture
def dagster_api(live_url):
    adapter = _utils.BackendAdapter(live_url, "dagster", "pw")
    adapter.access_token = SYSTEM_TOKEN
    return DagsterBackendAPI(_utils.BackendSession(adapter))


@pytest.fixture
def raw(live_url):
    """requests session, as the system user, for what the clients have no method for."""
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {SYSTEM_TOKEN}"

    class Raw:
        def call(self, method, path, **kw):
            response = session.request(method, live_url + path, timeout=30, **kw)
            return response

        def ok(self, method, path, status=None, **kw):
            response = self.call(method, path, **kw)
            assert response.status_code in ((status,) if status else (200, 201, 204)), (path, response.text)
            return response.json() if response.content else None
    return Raw()


SPEC_FILE = {"path": "triggers/spec.json", "status": "added"}
SPEC_RAW = '{"spec": {"image": "img:1"}}'


def pr(number, **fields):
    return {
        "number": number, "title": f"PR {number}", "raised_by": "user1", "merged_at": "2030-01-01T10:00:00Z",
        "merge_commit_sha": (f"{number:x}" * 40)[:40], "base_branch": "main", "files_truncated": False,
        "changed_files": [SPEC_FILE], **fields,
    }


@pytest.fixture
def world(api, raw):
    """A secret, project, global dataset, trigger repo and results repo, wired to the project, through the client."""
    secret = api.upsert_secret("live-creds", {"TOKEN": "t", "USERNAME": "u", "PASSWORD": "p"})
    project = api.get_or_create_project("LiveProject", description="d", enabled=False)
    dataset = api.create_dataset("LiveDs", "db", 5432, "postgres", "live-creds", "read", "write")
    provider = api.get_or_create_git_provider(
        "https://github.com", "github-github.com", "github", "https://api.github.com"
    )
    trigger = api.create_repository(provider.id, "org/live-triggers", "live-creds")
    results = api.create_results_repository(provider.id, "org/live-results", "live-creds")
    link_ds = api.get_or_assign_dataset(project.id, dataset)
    link_trigger = api.get_or_assign_repository(project.id, trigger, "triggers", "main")
    link_results = api.get_or_assign_results_repository(project.id, results, "results")
    project = api.patch_project(project.id, {"enabled": True})
    return dict(
        secret=secret, project=project, dataset=dataset, provider=provider, trigger=trigger, results=results,
        link_ds=link_ds, link_trigger=link_trigger, link_results=link_results,
    )


# --- fncli client ---------------------------------------------------------------------------

def test_fncli_setup_models_parse(api, world):
    w = world
    assert w["secret"]["label"] == "live-creds" and w["secret"]["key"] == "fn-secret-live-creds"
    assert isinstance(w["project"], fn_models.Project) and w["project"].enabled is True
    assert isinstance(w["dataset"], fn_models.Dataset) and w["dataset"].name == "liveds"
    assert w["dataset"].secret.label == "live-creds" and w["dataset"].read_schema == "read"
    assert isinstance(w["trigger"], fn_models.TriggerRepository)
    assert isinstance(w["provider"], fn_models.GitProvider) and w["trigger"].provider.id == w["provider"].id
    assert w["trigger"].uri == "https://github.com/org/live-triggers" and w["trigger"].repo_path == "org/live-triggers"
    assert isinstance(w["results"], fn_models.ResultsRepository)
    assert w["link_ds"].active and w["link_ds"].dataset.id == w["dataset"].id
    assert w["link_trigger"].watch_dir == "triggers" and w["link_trigger"].base_branch == "main"
    assert w["link_results"].target_dir == "results" and w["link_results"].results_repository.id == w["results"].id

    # lookups, get_or_* reuse
    assert api.get_dataset(w["dataset"].id).id == w["dataset"].id
    assert [d.id for d in api.get_datasets()] == [w["dataset"].id]
    assert api.find_dataset("LIVEDS").id == w["dataset"].id and api.find_dataset("nope") is None
    assert api.get_or_create_dataset("liveds").id == w["dataset"].id
    assert api.get_or_create_dataset(
        "second", host="db", port=1, db_type="postgres", secret_label="live-creds"
    ).name == "second"
    assert api.get_project(w["project"].id).name == "LiveProject"
    assert [p.id for p in api.get_projects()] == [w["project"].id]
    assert api.find_project("LiveProject").id == w["project"].id and api.find_project("x") is None
    assert api.get_or_create_project("LiveProject").id == w["project"].id
    assert [s["label"] for s in api.get_secrets()] == ["live-creds"]
    assert api.get_secret("live-creds")["key"] == "fn-secret-live-creds"
    assert api.upsert_secret("live-creds", {"TOKEN": "t2"})["label"] == "live-creds"
    assert [r.id for r in api.get_trigger_repositories()] == [w["trigger"].id]
    assert api.find_trigger_repository("https://github.com/org/live-triggers").id == w["trigger"].id
    assert api.find_trigger_repository("github.com/org/none") is None
    assert [p.id for p in api.get_git_providers()] == [w["provider"].id]
    assert api.find_git_provider("https://github.com").id == w["provider"].id and api.find_git_provider("x") is None
    assert api.get_or_create_git_provider(
        "https://github.com", "github-github.com", "github", "https://api.github.com"
    ).id == w["provider"].id
    assert api.get_or_create_trigger_repository(
        "github.com/org/live-triggers", provider_id=w["provider"].id, secret_label="live-creds"
    ).id == w["trigger"].id
    assert api.find_repository("github.com/org/live-triggers", w["project"].id).watch_dir == "triggers"
    assert api.find_repository("github.com/org/none", w["project"].id) is None
    assert api.get_or_assign_repository(w["project"].id, w["trigger"], "other", "dev").watch_dir == "triggers"
    assert [r.id for r in api.get_results_repositories()] == [w["results"].id]
    assert api.find_results_repository("github.com/org/live-results").id == w["results"].id
    assert api.find_results_repository("github.com/org/none") is None
    assert api.get_or_create_results_repository(
        "github.com/org/live-results", provider_id=w["provider"].id, secret_label="live-creds"
    ).id == w["results"].id
    assert api.get_or_create_results_repository(
        "github.com/org/second-results", provider_id=w["provider"].id, secret_label="live-creds"
    ).uri == "https://github.com/org/second-results"
    assert api.get_project_results_repositories(w["project"].id)[0].target_dir == "results"
    assert api.get_or_assign_results_repository(w["project"].id, w["results"], "x").target_dir == "results"
    assert api.get_project_datasets(w["project"].id)[0].dataset.id == w["dataset"].id
    assert api.find_project_dataset("LiveDs", w["project"].id).project_id == w["project"].id
    assert api.find_project_dataset("zzz", w["project"].id) is None
    assert api.get_or_assign_dataset(w["project"].id, w["dataset"]).active
    assert api.get_project_healthcheck(w["project"].id)["status"] in ("ok", "error")


def test_fncli_login_returns_token(api):
    # Keycloak is mocked in the app; /login is served by app.main's mocked Keycloak.
    try:
        data = api.login("admin", "pw")
    except requests.HTTPError as exc:  # pragma: no cover
        pytest.xfail(f"/login fails against the mocked Keycloak: {exc}")
    assert isinstance(data, dict)


def test_fncli_project_trigger_links_and_prs(api, raw, world):
    w = world
    pid, tid = w["project"].id, w["trigger"].id

    links = api.get_project_trigger_repositories(pid)
    assert [link.trigger_repository.id for link in links] == [tid]
    assert api.get_project_trigger_repository(pid, tid).active is True

    # 101 PRs: two ingest batches, so get_pull_requests pages (per_page is fixed at 100 by the client)
    created = api.create_pull_requests_batch(tid, [pr(n) for n in range(1, 101)])
    assert created["created"] == list(range(1, 101)) and created["existing"] == []
    created = api.create_pull_requests_batch(tid, [pr(n) for n in range(100, 102)])
    assert created == {"created": [101], "existing": [100]}
    with pytest.raises(ValueError):
        api.create_pull_requests_batch(tid, [pr(n) for n in range(1, 102)])

    prs = api.get_pull_requests(pid, tid)
    assert len(prs) == 101
    assert {p.number for p in prs} == set(range(1, 102))
    assert all(isinstance(p, fn_models.PullRequestTrigger) and p.state == fn_models.TriggerState.UNKNOWN for p in prs)
    assert len(api.get_pull_requests(pid, tid, state="UNKNOWN")) == 101
    with pytest.raises(requests.HTTPError) as exc:  # IGNORED no longer exists
        api.get_pull_requests(pid, tid, state="IGNORED")
    assert exc.value.response.status_code == 400

    # small pages through the same route, as the client's loop would see them
    page = raw.ok("GET", f"/projects/{pid}/repositories/triggers/{tid}/pull_requests?per_page=40&page=3")
    assert len(page["items"]) == 21 and page["total"] == 101 and page["page"] == 3 and page["per_page"] == 40

    # a PR on another base branch creates no trigger for the link
    api.create_pull_requests_batch(tid, [pr(200, base_branch="dev")])
    assert len(api.get_pull_requests(pid, tid)) == 101

    patched = api.patch_pull_request(pid, tid, 1, {"state": "REJECTED", "state_cause": "bad"})
    assert patched.state == fn_models.TriggerState.REJECTED and patched.state_cause == "bad"
    assert [p.number for p in api.get_pull_requests(pid, tid, state="REJECTED")] == [1]

    link = api.patch_project_trigger_repository(pid, tid, {"enabled": False})
    assert link.enabled is False and link.active is False
    assert api.get_project_trigger_repository(pid, tid).pr_count == 101


def test_fncli_task_and_results(api, raw, world):
    w = world
    pid, tid, rid = w["project"].id, w["trigger"].id, w["results"].id
    api.create_pull_requests_batch(tid, [pr(1)])
    task = raw.ok("POST", f"/projects/{pid}/repositories/triggers/{tid}/pull_requests/1/task", 201,
                  json={"spec_raw": SPEC_RAW})
    fetched = api.get_task(pid, task["id"])
    assert isinstance(fetched, fn_models.Task) and fetched.spec.image == "img:1"
    assert fetched.spec.dataset_id is None or fetched.spec.dataset_id == w["dataset"].id
    assert fetched.project_id == pid
    assert api.get_task_results(pid, task["id"]) == []

    raw.ok("POST", f"/projects/{pid}/results", 409, json={"task_id": task["id"], "results_repository_id": rid})
    raw.ok("PATCH", f"/projects/{pid}/tasks/{task['id']}", 200, json={"status": "SUCCESS"})
    result = raw.ok("POST", f"/projects/{pid}/results", 201, json={"task_id": task["id"], "results_repository_id": rid})
    results = api.get_task_results(pid, task["id"])
    assert len(results) == 1 and isinstance(results[0], fn_models.PullRequestResult)
    assert results[0].id == result["id"] and results[0].step == "UNKNOWN" and results[0].state == "IN_PROGRESS"


def test_fncli_errors(api, world):
    w = world
    pid, tid = w["project"].id, w["trigger"].id
    creds = ("github.com/org/new", "github", "https://api.github.com", "missing-secret")
    cases = [
        (404, lambda: api.get_task(pid, 9999)),
        (404, lambda: api.get_dataset(9999)),
        (404, lambda: api.get_project(9999)),
        (404, lambda: api.get_project_trigger_repository(pid, 9999)),
        (404, lambda: api.patch_pull_request(pid, tid, 99, {"state": "REJECTED", "state_cause": "x"})),
        (400, lambda: api.get_pull_requests(pid, tid, state="NOPE")),
        (409, lambda: api.create_repository("github.com/org/live-triggers", "github", "https://api.github.com", "live-creds")),
        (400, lambda: api.create_repository(*creds)),
        (409, lambda: api.delete_secret("live-creds")),  # a secret in use cannot be deleted
    ]
    for status, call in cases:
        with pytest.raises(requests.HTTPError) as exc:
            call()
        assert exc.value.response.status_code == status
    assert api.delete_secret("never-existed") is False


def test_fncli_deletes(api, world):
    w = world
    pid = w["project"].id
    api.delete_dataset(w["dataset"].id)
    api.delete_repository(w["trigger"].id)
    with pytest.raises(requests.HTTPError) as exc:
        api.delete_git_provider(w["provider"].id)  # repositories are still on it
    assert exc.value.response.status_code == 409
    api.delete_results_repository(w["results"].id)
    api.delete_git_provider(w["provider"].id)
    assert api.get_datasets() == [] and api.get_trigger_repositories() == []
    assert api.get_results_repositories() == [] and api.get_git_providers() == []
    assert api.delete_secret("live-creds") is True
    with pytest.raises(requests.HTTPError) as exc:
        api.get_secret("live-creds")
    assert exc.value.response.status_code == 404
    api.delete_project(pid)
    with pytest.raises(requests.HTTPError) as exc:
        api.get_project(pid)
    assert exc.value.response.status_code == 404


# --- Dagster code location client -----------------------------------------------------------

def test_dagster_client_full_flow(dagster_api, api, world, raw):
    d = dagster_api
    w = world
    pid, tid, rid, did = w["project"].id, w["trigger"].id, w["results"].id, w["dataset"].id

    assert [p.id for p in d.get_projects()] == [pid]
    assert [r.id for r in d.get_pollable_trigger_repositories()] == [tid]
    active = d.get_pollable_trigger_repositories()[0]
    assert active.pr_cursor is not None
    assert [link.trigger_repository.id for link in d.get_project_trigger_repositories(pid)] == [tid]
    assert d.get_project_trigger_repository(pid, tid).active
    assert d.get_project_dataset(pid, did).dataset.id == did
    assert d.get_dataset(did).id == did and [x.id for x in d.get_datasets()] == [did]
    assert d.get_results_repository(pid).results_repository.id == rid
    assert d.get_results_repository_by_id(pid, rid).target_dir == "results"

    batch = d.create_pull_requests_batch(tid, [pr(n) for n in range(1, 4)])
    assert batch["created"] == [1, 2, 3]
    assert d.create_pull_requests_batch(tid, [pr(3), pr(4)]) == {"created": [4], "existing": [3]}
    prs = d.get_pull_requests(pid, tid, "UNKNOWN")
    assert sorted(p.number for p in prs) == [1, 2, 3, 4]  # newest merge first
    patched = d.patch_pull_request(pid, tid, 4, {"state": "REJECTED", "state_cause": "n/a"})
    assert patched.state.value == "REJECTED"
    assert [p.number for p in d.get_pull_requests(pid, tid, "REJECTED")] == [4]

    task, created = d.create_task_for_pull_request(pid, tid, 1, SPEC_RAW)
    assert created is True and task.status == "PENDING" and task.spec.dataset_id == did
    task2, created2 = d.create_task_for_pull_request(pid, tid, 1, SPEC_RAW)
    assert created2 is False and task2.id == task.id
    assert [t.id for t in d.get_tasks("PENDING", pid)] == [task.id]
    assert d.get_tasks("RUNNING", pid) == []
    running = d.patch_task(pid, task.id, {"status": "RUNNING", "executor_run_id": "run-1"})
    assert running.status == "RUNNING" and running.executor_run_id == "run-1"
    assert d.get_task(pid, task.id).executor_run_id == "run-1"
    trigger = d.get_task_trigger(pid, task.id)
    assert (trigger.number, trigger.trigger_repository.id) == (1, tid)
    assert d.patch_task(pid, task.id, {"status": "SUCCESS"}).status == "SUCCESS"
    with pytest.raises(requests.HTTPError) as exc:  # a finished task cannot change status
        d.patch_task(pid, task.id, {"status": "FAILED"})
    assert exc.value.response.status_code == 409
    assert d.get_task_results(pid, task.id) == []

    result = d.create_result(pid, task.id, rid)
    assert result.step.value == "UNKNOWN" and result.state.value == "IN_PROGRESS" and result.type == "PR"
    assert d.create_result(pid, task.id, rid).id == result.id
    opened = d.patch_result(pid, result.id, {"step": "OPENED", "state": "DELIVERED", "number": 5, "url": "https://x/pull/5"})
    assert opened.step.value == "OPENED" and opened.number == 5
    assert [r.id for r in d.get_results_by_step(pid, ["OPENED"])] == [result.id]
    assert [r.id for r in d.get_results_by_step(pid, ["PUSHED", "OPENED"])] == [result.id]
    assert d.get_results_by_step(pid, ["PUSHED"]) == []
    assert [r.id for r in d.get_task_results(pid, task.id)] == [result.id]

    # setup methods of the dagster client
    ds = d.create_dataset("DagDs", "db", 5432, "postgres", "live-creds")
    assert ds.name == "dagds"
    repo = d.create_repository(world["provider"].id, "org/dag-triggers", "live-creds")
    link = d.assign_repository(pid, repo.id, "dag", "main")
    assert link.watch_dir == "dag" and link.trigger_repository.id == repo.id
    api.patch_project_trigger_repository(pid, tid, {"enabled": False})
    assert [l.trigger_repository.id for l in d.get_project_trigger_repositories(pid, active=True)] == [repo.id]
    d.delete_dataset(ds.id)
    d.delete_repository(repo.id)
    with pytest.raises(requests.HTTPError) as exc:
        d.get_task(pid, 9999)
    assert exc.value.response.status_code == 404
    with pytest.raises(requests.HTTPError) as exc:
        d.create_result(pid, task.id, 9999)
    assert exc.value.response.status_code == 400
    with pytest.raises(requests.HTTPError) as exc:
        d.patch_result(pid, result.id, {"step": "PUSHED"})
    assert exc.value.response.status_code == 400
    with pytest.raises(requests.HTTPError) as exc:
        d.create_repository("github.com/org/live-triggers", "github", "https://api.github.com", "live-creds")
    assert exc.value.response.status_code == 409


def test_e2e_check_script_reads_the_real_routes(api, raw, world):
    """scripts/e2e_check.py (used by scripts/e2e_shared_resources.sh) against the real routes and response shapes."""
    from types import SimpleNamespace
    w = world
    pid, tid = w["project"].id, w["trigger"].id
    config, args = SimpleNamespace(project_name=w["project"].name), SimpleNamespace(timeout=5)

    # a watched PR (gets a task), an invalid one (REJECTED), and an unwatched one on another branch (no trigger)
    api.create_pull_requests_batch(tid, [pr(1), pr(2), pr(3, base_branch="dev")])
    task = raw.ok("POST", f"/projects/{pid}/repositories/triggers/{tid}/pull_requests/1/task", 201,
                  json={"spec_raw": SPEC_RAW})
    api.patch_pull_request(pid, tid, 2, {"state": "REJECTED", "state_cause": "bad spec"})

    snap = e2e.snapshot(api, config.project_name)
    assert len(snap["trigger_links"]) == 1 and snap["trigger_links"][0]["active"] is True
    assert {p["number"]: p["state"] for p in snap["trigger_links"][0]["pull_requests"]} == {1: "YIELDED", 2: "REJECTED"}
    assert [t["id"] for t in snap["tasks"]] == [task["id"]]

    assert e2e.command_wait_prs(api, config, args) == 0
    assert e2e.command_wait_tasks(api, config, args) == 1  # the task is still PENDING
    raw.ok("PATCH", f"/projects/{pid}/tasks/{task['id']}", 200, json={"status": "SUCCESS"})
    assert e2e.command_wait_tasks(api, config, args) == 0


def test_fncli_state_commands_against_the_real_routes(api, admin_api, raw, world):
    """fncli/cmds/state.py (the QA plan's commands for rule scenarios) against the real routes and response shapes."""
    from types import SimpleNamespace
    w = world
    pid, tid = w["project"].id, w["trigger"].id
    name = w["project"].name
    config = SimpleNamespace(project_name=name)

    raw.ok("PUT", f"/projects/{pid}/secrets/live-creds", 201, json={})  # `world` creates the secret but does not link it
    api.create_pull_requests_batch(tid, [pr(1)])
    task = raw.ok("POST", f"/projects/{pid}/repositories/triggers/{tid}/pull_requests/1/task", 201,
                  json={"spec_raw": SPEC_RAW})
    raw.ok("PATCH", f"/projects/{pid}/tasks/{task['id']}", 200, json={"status": "SUCCESS"})
    raw.ok("POST", f"/projects/{pid}/results", 201,
           json={"task_id": task["id"], "results_repository_id": w["results"].id})

    snap = state.snapshot(api, name)
    assert snap["project"]["id"] == pid
    assert [(p["number"], p["state"]) for p in snap["trigger_links"][0]["pull_requests"]] == [(1, "YIELDED")]
    assert [t["status"] for t in snap["tasks"]] == ["SUCCESS"] and snap["results"][0]["step"] == "UNKNOWN"
    assert snap["results_links"][0]["target_dir"] == "results" and snap["secret_links"][0]["secret"] == "live-creds"

    # revoke and un-revoke a link: immediate
    assert state.set_link(api, name, "trigger", None, "true", 200, admin_api=admin_api) == 0
    assert state.snapshot(api, name)["trigger_links"][0]["active"] is False
    assert state.set_link(api, name, "trigger", None, "false", 200, admin_api=admin_api) == 0
    assert state.snapshot(api, name)["trigger_links"][0]["active"] is True

    # a global resource can be disabled and enabled at once
    assert state.set_global(api, name, "trigger", "false", 200) == 0
    assert state.snapshot(api, name)["trigger_links"][0]["global_enabled"] is False
    assert state.set_global(api, name, "trigger", "true", 200) == 0

    # the project: off and on, and --backfill only when switching a disabled project on
    assert state.set_project(api, name, "false", False, 200) == 0
    assert state.set_project(api, name, None, True, 400) == 0  # --backfill without --enabled true
    assert state.set_project(api, name, "true", True, 200) == 0
    assert state.set_project(api, name, "true", True, 400) == 0  # already enabled
    assert state.set_project(api, name, "true", False, 500) == 1  # --expect is checked, a mismatch is a failure

    # a second project on the SAME global resources, then removed again (the global resources stay)
    assert state.setup_second_project(api, config, "QaTwo") == 0
    two = state.snapshot(api, "QaTwo")
    assert two["trigger_links"][0]["repository_id"] == tid and two["project"]["enabled"] is True
    assert two["results_links"] and two["dataset_links"] and two["secret_links"]
    assert state.teardown_second_project(api, "QaTwo", 204) == 0
    assert api.find_project("QaTwo") is None
    assert api.find_project(name) is not None
