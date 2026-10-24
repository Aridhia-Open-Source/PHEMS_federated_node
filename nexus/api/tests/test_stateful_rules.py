"""
Random sequences of actions against the webserver, checked against a small model of the rules (Hypothesis stateful testing).
The rules are those in docs/architecture/revoke-and-enabled.md (enabled and revoked) and ADRs 0008 and 0011
(project/decisions/0008-enabled-revoked-and-soft-delete.md, 0011-pull-requests-stored-once-fan-out-and-cursors.md: the cursor, fan-out and backfill).
It needs `hypothesis` (pinned in requirements-dev.txt) and the usual test database.

One project, linked to one global trigger repository. Hypothesis builds random sequences of the actions below and, after
every action, compares the real state (the API) with the model. A failing sequence is shrunk to the shortest that fails.

ACTIONS (rules)
  merge_pr(matching)          a PR is merged at the provider (the model's "git server"); matching ones add a spec file under watch_dir
  ingest()                    what the ingest sensor does: post the PRs merged after the newest stored one, 100 at most
  ingest_when_inactive()      the same call to a global repository that is disabled or revoked is refused (400) and stores nothing
  evaluate_one()              what the evaluate sensor does: create the task of an UNKNOWN trigger (201 if the link is active and the
                              project is enabled and not revoked, else 409 and nothing changes)
  progress_task()             a task moves PENDING -> QUEUED -> RUNNING -> SUCCESS or FAILED (the run-status sensors)
  finished_task_is_final()    a finished task cannot change to another status (409)
  set_link_enabled(v)         turn the link on or off: always 200, no drain needed
  set_link_revoked(v)         revoke or re-grant the link: always 200, takes effect at once
  set_global_enabled(v)       turn the global repository on or off: always 200
  set_global_revoked(v)       revoke or re-grant the global repository for every project: always 200
  set_project_enabled(v, b)   turn the project on or off: always 200; off -> on skips the gap, or with backfill creates the missed triggers
  set_project_revoked(v)      revoke or re-grant the project: always 200; re-granting skips the gap
  refused_backfill(v)         backfill with anything but "enabled": true on a disabled project is refused (400)

INVARIANTS (checked after every action)
  triggers_match_model        the project's triggers (number -> state) are exactly the model's
  stored_prs_match_model      the repository has stored exactly the PRs the model says
  tasks_match_model           the project's tasks (id -> status) are exactly the model's; no PR has two tasks
  link_active_matches_model   the link is active iff the global repository and the link are on and not revoked
  flags_match_model           the enabled and revoked flags of the project, the global repository and the link are the model's

THE MODEL'S RULES, in words (each one is a decision; the documents above are the reference)
  - A stored PR gets a trigger for the link only if it matches (a spec file under watch_dir), the link is active, and the project is
    enabled and not revoked when it is stored.
  - No replay: whenever the link, the global repository or the project becomes usable again (switched on or re-granted), its cursor
    moves to now. Every PR that exists at that moment is stored when ingested but never gets a trigger; PRs merged after it do.
  - An inactive link, or a revoked project, refuses to create a task (409) and the trigger stays UNKNOWN.
  - A global repository that is disabled or revoked refuses new PRs entirely (400). The sensor fetches them again once it is back,
    the ingest cursor being the newest stored PR.
  - Switching any flag needs no draining: it is always 200, a revoke takes effect at once, and a revoke never changes `enabled`.
  - Enabling a disabled project with "backfill": true leaves the cursor where it is and gives its links that accept triggers a trigger
    for every stored PR that matches, is after the cursor and has none yet. "backfill" with anything else is a 400 and changes nothing.
"""

import json
import os
from datetime import datetime, timedelta
from unittest import mock

from hypothesis import HealthCheck, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from sqlalchemy.orm.session import close_all_sessions

from app import create_app
from app.helpers.base_model import db
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.task_status import TASK_MOVES
from app.models.trigger_repository import TriggerRepository
from tests.conftest import new_repo

UNFINISHED = {"PENDING", "QUEUED", "RUNNING"}
FINAL = {"SUCCESS", "FAILED", "CANCELED"}
WATCH_DIR = "triggers"
SPEC_RAW = json.dumps({"spec": {"image": "i:1"}})
# Fake clock: the route moves the link's cursor to "now" when the link or the repository becomes active again, so PR merge times and that
# "now" come from one machine-controlled clock (one minute per tick, after the link's real creation time so every PR is in scope
# of the creation cursor). The route's clock is patched in __init__.
CLOCK_START = datetime.utcnow().replace(microsecond=0) + timedelta(days=1)


def pr_body(number: int, matching: bool, merged_at: datetime) -> dict:
    """A pull request as the ingest posts it. Merge times increase with the number, so the number is also the cursor."""
    path = f"{WATCH_DIR}/spec{number}.json" if matching else f"docs/notes{number}.md"
    return {
        "number": number, "title": f"PR {number}", "raised_by": "user",
        "merged_at": merged_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "merge_commit_sha": f"{number:040x}", "base_branch": "main", "files_truncated": False,
        "changed_files": [{"path": path, "status": "added"}],
    }


class TriggerLinkMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.app = create_app()
        self.app.testing = True
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()  # Hypothesis can build a machine it never tears down: start from empty tables
        db.create_all()
        self.tick = 0
        clock = mock.patch("app.helpers.pull_request_fanout.now_ts", lambda: CLOCK_START + timedelta(minutes=self.tick))
        clock.start()
        self.clock = clock
        self.client = self.app.test_client()
        self.headers = {"Content-Type": "application/json", "Authorization": "Bearer admin_token"}
        self.system_headers = {"Content-Type": "application/json", "Authorization": "Bearer system_token"}

        secret = Secret(label="stateful-creds", provider=SecretProviderType.K8S)
        secret.add()
        self.repo_id = new_repo(TriggerRepository, "github.com/org/stateful", secret.id).id
        project = self.call("post", "/projects", {"name": "Stateful", "enabled": True})
        assert project.status_code == 201, project.json()
        self.project_id = project.json()["id"]
        link = self.call("put", self.link_url, {"watch_dir": WATCH_DIR})
        assert link.status_code == 201, link.json()

        # The model, started from what the API reports: only the facts, not the rules, are read back
        project_json = self.call("get", f"/projects/{self.project_id}").json()
        self.link_enabled = link.json()["enabled"]
        self.link_revoked = link.json()["revoked"]
        self.project_enabled = project_json["enabled"]
        self.project_revoked = project_json["revoked"]
        repo_json = self.call("get", f"/global/repositories/triggers/{self.repo_id}").json()
        self.global_enabled = repo_json["enabled"]
        self.global_revoked = repo_json["revoked"]
        self.provider = []          # PRs merged at the git server: {"number", "matching", "merged_at"}
        self.skip_before = 0        # PRs numbered up to this existed when the link, repository or project last became usable again
        self.stored = {}            # number -> matching, what the repository has stored
        self.triggers = {}          # number -> state, the project's triggers
        self.tasks = {}             # task id -> status

    def teardown(self):
        self.clock.stop()
        close_all_sessions()
        db.drop_all()
        self.context.pop()

    # ----------------------------------------------------------------------------- helpers

    @property
    def link_url(self) -> str:
        return f"/projects/{self.project_id}/repositories/triggers/{self.repo_id}"

    def call(self, method: str, url: str, body: dict | None = None):
        return getattr(self.client, method)(url, json=body, headers=self.headers)

    def call_as_system(self, method: str, url: str, body: dict):
        """The state-machine writes (ingest, task creation, task status) are the system user's."""
        return getattr(self.client, method)(url, json=body, headers=self.system_headers)

    @property
    def global_active(self) -> bool:
        return self.global_enabled and not self.global_revoked

    @property
    def link_active(self) -> bool:
        return self.global_active and self.link_enabled and not self.link_revoked

    @property
    def project_accepts(self) -> bool:
        return self.project_enabled and not self.project_revoked

    def skip_gap_if_activated(self, was_active: bool):
        """A link that has become active again gives no trigger to the PRs that exist now."""
        if self.link_active and not was_active:
            self.skip_before = len(self.provider)

    # ----------------------------------------------------------------------------- the git server and the sensors

    @rule(matching=st.booleans())
    def merge_pr(self, matching):
        self.tick += 1
        self.provider.append({
            "number": len(self.provider) + 1, "matching": matching, "merged_at": CLOCK_START + timedelta(minutes=self.tick),
        })

    @precondition(lambda self: self.global_active)
    @rule()
    def ingest(self):
        cursor = max(self.stored, default=0)
        batch = [p for p in self.provider if p["number"] > cursor][:100]
        response = self.call_as_system(
            "post", f"/global/repositories/triggers/{self.repo_id}/pull_requests",
            {"pull_requests": [pr_body(p["number"], p["matching"], p["merged_at"]) for p in batch]})
        assert response.status_code == 201, response.json()
        assert sorted(response.json()["created"]) == [p["number"] for p in batch]
        assert response.json()["existing"] == []
        for pull in batch:
            self.stored[pull["number"]] = pull["matching"]
            if pull["matching"] and self.link_active and self.project_accepts and pull["number"] > self.skip_before:
                self.triggers[pull["number"]] = "UNKNOWN"

    @precondition(lambda self: not self.global_active)
    @rule()
    def ingest_when_inactive(self):
        response = self.call_as_system(
            "post", f"/global/repositories/triggers/{self.repo_id}/pull_requests",
            {"pull_requests": [pr_body(p["number"], p["matching"], p["merged_at"]) for p in self.provider[:1]]})
        assert response.status_code == 400, response.json()

    @precondition(lambda self: "UNKNOWN" in self.triggers.values())
    @rule(data=st.data())
    def evaluate_one(self, data):
        number = data.draw(st.sampled_from(sorted(n for n, s in self.triggers.items() if s == "UNKNOWN")))
        response = self.call_as_system("post", f"{self.link_url}/pull_requests/{number}/task", {"spec_raw": SPEC_RAW})
        if self.link_active and self.project_accepts:
            assert response.status_code == 201, response.json()
            self.triggers[number] = "YIELDED"
            self.tasks[response.json()["id"]] = "PENDING"
        else:
            assert response.status_code == 409, response.json()

    @precondition(lambda self: UNFINISHED & set(self.tasks.values()))
    @rule(data=st.data())
    def progress_task(self, data):
        task_id = data.draw(st.sampled_from(sorted(t for t, s in self.tasks.items() if s in UNFINISHED)))
        status = data.draw(st.sampled_from(sorted(TASK_MOVES[self.tasks[task_id]])))  # forward only
        response = self.call_as_system("patch", f"/projects/{self.project_id}/tasks/{task_id}", {"status": status})
        assert response.status_code == 200, response.json()
        self.tasks[task_id] = status

    @precondition(lambda self: FINAL & set(self.tasks.values()))
    @rule(data=st.data(), status=st.sampled_from(["PENDING", "QUEUED", "RUNNING", "SUCCESS", "FAILED"]))
    def finished_task_is_final(self, data, status):
        task_id = data.draw(st.sampled_from(sorted(t for t, s in self.tasks.items() if s in FINAL)))
        response = self.call_as_system("patch", f"/projects/{self.project_id}/tasks/{task_id}", {"status": status})
        # The same status again is allowed, a different one is refused
        assert response.status_code == (200 if status == self.tasks[task_id] else 409), response.json()

    # ----------------------------------------------------------------------------- the flags

    @rule(value=st.booleans())
    def set_link_enabled(self, value):
        was = self.link_active
        self.tick += 1  # the route reads the clock during the call: the cursor lands after every PR merged so far
        response = self.call("patch", self.link_url, {"enabled": value})
        assert response.status_code == 200, response.json()
        self.link_enabled = value
        self.skip_gap_if_activated(was)

    @rule(value=st.booleans(), backfill=st.sampled_from([None, False, True]))
    def set_project_enabled(self, value, backfill):
        switched_on = value and not self.project_enabled
        body = {"enabled": value}
        if switched_on and backfill is not None:
            body["backfill"] = backfill
        self.tick += 1
        response = self.call("patch", f"/projects/{self.project_id}", body)
        assert response.status_code == 200, response.json()
        self.project_enabled = value
        if switched_on and backfill:  # a revoked project or an inactive link gets nothing from the backfill
            if self.link_active and not self.project_revoked:
                for number, matching in self.stored.items():
                    if matching and number > self.skip_before and number not in self.triggers:
                        self.triggers[number] = "UNKNOWN"
        elif switched_on:
            self.skip_before = len(self.provider)

    @rule(enabled=st.sampled_from([None, False, True]))
    def refused_backfill(self, enabled):
        if enabled and not self.project_enabled:
            return  # that is set_project_enabled
        body = {"backfill": True} if enabled is None else {"enabled": enabled, "backfill": True}
        assert self.call("patch", f"/projects/{self.project_id}", body).status_code == 400

    @rule(value=st.booleans())
    def set_link_revoked(self, value):
        was = self.link_active
        self.tick += 1
        response = self.call("patch", self.link_url, {"revoked": value})
        assert response.status_code == 200, response.json()
        self.link_revoked = value
        self.skip_gap_if_activated(was)

    @rule(value=st.booleans())
    def set_global_enabled(self, value):
        was = self.global_active
        self.tick += 1  # the route reads the clock during the call: the cursor lands after every PR merged so far
        response = self.call("patch", f"/global/repositories/triggers/{self.repo_id}", {"enabled": value})
        assert response.status_code == 200, response.json()
        self.global_enabled = value
        if self.global_active and not was:
            self.skip_before = len(self.provider)

    @rule(value=st.booleans())
    def set_global_revoked(self, value):
        was = self.global_active
        self.tick += 1
        response = self.call("patch", f"/global/repositories/triggers/{self.repo_id}", {"revoked": value})
        assert response.status_code == 200, response.json()
        self.global_revoked = value
        if self.global_active and not was:
            self.skip_before = len(self.provider)

    @rule(value=st.booleans())
    def set_project_revoked(self, value):
        was_revoked = self.project_revoked
        self.tick += 1
        response = self.call("patch", f"/projects/{self.project_id}", {"revoked": value})
        assert response.status_code == 200, response.json()
        self.project_revoked = value
        if was_revoked and not value:
            self.skip_before = len(self.provider)

    # ----------------------------------------------------------------------------- invariants

    @invariant()
    def triggers_match_model(self):
        page = self.call("get", f"{self.link_url}/pull_requests?per_page=200").json()
        assert {item["number"]: item["state"] for item in page["items"]} == self.triggers

    @invariant()
    def stored_prs_match_model(self):
        listing = self.call("get", f"/global/repositories/triggers/{self.repo_id}/pull_requests?per_page=200").json()
        assert listing["total"] == len(self.stored)

    @invariant()
    def tasks_match_model(self):
        page = self.call("get", f"/projects/{self.project_id}/tasks?per_page=200").json()
        assert {task["id"]: task["status"] for task in page["tasks"]} == self.tasks
        links = self.call("get", f"{self.link_url}/pull_requests?per_page=200").json()["items"]
        task_ids = [item["task_id"] for item in links if item["task_id"] is not None]
        assert len(task_ids) == len(set(task_ids)), "two triggers share a task"

    @invariant()
    def link_active_matches_model(self):
        assert self.call("get", self.link_url).json()["active"] == self.link_active

    @invariant()
    def flags_match_model(self):
        project = self.call("get", f"/projects/{self.project_id}").json()
        repo = self.call("get", f"/global/repositories/triggers/{self.repo_id}").json()
        link = self.call("get", self.link_url).json()
        assert (project["enabled"], project["revoked"]) == (self.project_enabled, self.project_revoked)
        assert (repo["enabled"], repo["revoked"]) == (self.global_enabled, self.global_revoked)
        assert (link["enabled"], link["revoked"]) == (self.link_enabled, self.link_revoked)


# The default is a quick smoke run (about 45 s). STATEFUL_DEEP=1 runs the deep search (about 7 minutes); run it before
# relying on this file.
DEEP = os.environ.get("STATEFUL_DEEP") == "1"
TriggerLinkMachine.TestCase.settings = settings(
    max_examples=300 if DEEP else 50, stateful_step_count=40 if DEEP else 25, deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
TestTriggerLinkRules = TriggerLinkMachine.TestCase
