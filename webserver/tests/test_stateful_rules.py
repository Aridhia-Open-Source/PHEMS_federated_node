"""
Random sequences of actions against the webserver, checked against a small model of the rules (Hypothesis stateful testing).
NOT RUN: written for review. It needs `hypothesis` (not yet in the dev requirements) and the usual test database.

One project, linked to one global trigger repository. Hypothesis builds random sequences of the actions below and, after
every action, compares the real state (the API) with the model. A failing sequence is shrunk to the shortest that fails.

ACTIONS (rules)
  merge_pr(matching)          a PR is merged at the provider (the model's "git server"); matching ones add a spec file under watch_dir
  ingest()                    what the ingest sensor does: post the PRs merged after the newest stored one, 100 at most
  ingest_when_disabled()      the same call to a disabled global repository is refused (400) and stores nothing
  evaluate_one()              what the evaluate sensor does: create the task of an UNKNOWN trigger (201 if the link is active, else 409)
  progress_task()             a task moves PENDING -> QUEUED -> RUNNING -> SUCCESS or FAILED (the run-status sensors)
  finished_task_is_final()    a finished task cannot change to another status (409)
  set_locked(v)               lock or unlock the project: always allowed
  set_link_enabled(v)         turn the link on or off: 200 only if the project is locked and drained, else 409
  set_link_revoked(v)         revoke or re-grant the link: always 200, takes effect at once
  set_global_enabled(v)       turn the global repository on or off: 200 only if the project is locked and drained, else 409; off -> on skips the gap (M6)

INVARIANTS (checked after every action)
  triggers_match_model        the project's triggers (number -> state) are exactly the model's
  stored_prs_match_model      the repository has stored exactly the PRs the model says
  tasks_match_model           the project's tasks (id -> status) are exactly the model's; no PR has two tasks
  link_active_matches_model   the link is active iff the global repository, the link are on and the link is not revoked

THE MODEL'S RULES (to review; each one is a decision, not just a description of the code)
  M1  A stored PR gets a trigger for the link only if it matches (spec file under watch_dir) and the link is active when it is stored.
  M2  SELF-HEALING: whenever the LINK becomes active (link enabled, link re-granted), every stored matching PR that has no trigger
      gets one (backfill), except the ones M6 skips. A link made active by the GLOBAL repository being enabled does not backfill.
  M3  An inactive link refuses to create a task (409) and the trigger stays UNKNOWN.
  M4  Changing the link's or the repository's enabled flag needs the project locked and drained (no task PENDING/QUEUED/RUNNING).
      Results are not modelled yet, so drained = no unfinished task.
  M5  Revoking needs neither the lock nor draining.
  M6  A disabled global repository refuses new PRs entirely (the sensor fetches them again once it is back on, the ingest cursor
      being the newest stored PR). Switching it back on moves the link's cursor to now: every PR that exists at that moment is still
      stored when ingested but never gets a trigger (not at ingest, not by a backfill); PRs merged after it do.
"""

import json
from datetime import datetime, timedelta
from unittest import mock

from hypothesis import HealthCheck, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from sqlalchemy.orm.session import close_all_sessions

from app import create_app
from app.helpers.base_model import db
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.trigger_repository import TriggerRepository
from tests.conftest import new_repo

UNFINISHED = {"PENDING", "QUEUED", "RUNNING"}
FINAL = {"SUCCESS", "FAILED", "CANCELED"}
WATCH_DIR = "triggers"
SPEC_RAW = json.dumps({"spec": {"image": "i:1"}})
# Fake clock: the route moves the link's cursor to "now" when the repository is switched back on, so PR merge times and that
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
        db.create_all()
        self.tick = 0
        clock = mock.patch("app.helpers.pull_request_fanout.now_ts", lambda: CLOCK_START + timedelta(minutes=self.tick))
        clock.start()
        self.clock = clock
        self.client = self.app.test_client()
        self.headers = {"Content-Type": "application/json", "Authorization": "Bearer admin_token"}

        secret = Secret(label="stateful-creds", provider=SecretProviderType.K8S)
        secret.add()
        self.repo_id = new_repo(TriggerRepository, "github.com/org/stateful", secret.id).id
        project = self.call("post", "/projects", {"name": "Stateful"})
        assert project.status_code == 201, project.json
        self.project_id = project.json["id"]
        link = self.call("put", self.link_url, {"watch_dir": WATCH_DIR})
        assert link.status_code == 201, link.json

        # The model, started from what the API reports: only the facts, not the rules, are read back
        self.locked = project.json["locked"]
        self.link_enabled = link.json["enabled"]
        self.link_revoked = link.json["revoked"]
        self.global_enabled = self.call("get", f"/global/repositories/triggers/{self.repo_id}").json["enabled"]
        self.provider = []          # PRs merged at the git server: {"number", "matching", "merged_at"}
        self.skip_before = 0        # M6: PRs numbered up to this existed when the repository was last switched back on
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

    @property
    def link_active(self) -> bool:
        return self.global_enabled and self.link_enabled and not self.link_revoked

    @property
    def drained(self) -> bool:
        return not UNFINISHED & set(self.tasks.values())

    def backfill_if_activated(self, was_active: bool):
        """M2: a link that has become active backfills the triggers of every stored matching PR it is missing, M6 aside."""
        if self.link_active and not was_active:
            for number, matching in self.stored.items():
                if matching and number > self.skip_before and number not in self.triggers:
                    self.triggers[number] = "UNKNOWN"

    # ----------------------------------------------------------------------------- the git server and the sensors

    @rule(matching=st.booleans())
    def merge_pr(self, matching):
        self.tick += 1
        self.provider.append({
            "number": len(self.provider) + 1, "matching": matching, "merged_at": CLOCK_START + timedelta(minutes=self.tick),
        })

    @precondition(lambda self: self.global_enabled)
    @rule()
    def ingest(self):
        cursor = max(self.stored, default=0)
        batch = [p for p in self.provider if p["number"] > cursor][:100]
        response = self.call("post", f"/global/repositories/triggers/{self.repo_id}/pull_requests",
                             {"pull_requests": [pr_body(p["number"], p["matching"], p["merged_at"]) for p in batch]})
        assert response.status_code == 201, response.json
        assert sorted(response.json["created"]) == [p["number"] for p in batch]
        assert response.json["existing"] == []
        for pull in batch:
            self.stored[pull["number"]] = pull["matching"]
            if pull["matching"] and self.link_active and pull["number"] > self.skip_before:  # M1, M6
                self.triggers[pull["number"]] = "UNKNOWN"

    @precondition(lambda self: not self.global_enabled)
    @rule()
    def ingest_when_disabled(self):  # M6
        response = self.call("post", f"/global/repositories/triggers/{self.repo_id}/pull_requests",
                             {"pull_requests": [pr_body(p["number"], p["matching"], p["merged_at"]) for p in self.provider[:1]]})
        assert response.status_code == 400, response.json

    @precondition(lambda self: "UNKNOWN" in self.triggers.values())
    @rule(data=st.data())
    def evaluate_one(self, data):
        number = data.draw(st.sampled_from(sorted(n for n, s in self.triggers.items() if s == "UNKNOWN")))
        response = self.call("post", f"{self.link_url}/pull_requests/{number}/task", {"spec_raw": SPEC_RAW})
        if self.link_active:
            assert response.status_code == 201, response.json
            self.triggers[number] = "YIELDED"
            self.tasks[response.json["id"]] = "PENDING"
        else:  # M3
            assert response.status_code == 409, response.json

    @precondition(lambda self: UNFINISHED & set(self.tasks.values()))
    @rule(data=st.data(), status=st.sampled_from(["QUEUED", "RUNNING", "SUCCESS", "FAILED"]))
    def progress_task(self, data, status):
        task_id = data.draw(st.sampled_from(sorted(t for t, s in self.tasks.items() if s in UNFINISHED)))
        response = self.call("patch", f"/projects/{self.project_id}/tasks/{task_id}", {"status": status})
        assert response.status_code == 200, response.json
        self.tasks[task_id] = status

    @precondition(lambda self: FINAL & set(self.tasks.values()))
    @rule(data=st.data(), status=st.sampled_from(["PENDING", "QUEUED", "RUNNING", "SUCCESS", "FAILED"]))
    def finished_task_is_final(self, data, status):
        task_id = data.draw(st.sampled_from(sorted(t for t, s in self.tasks.items() if s in FINAL)))
        response = self.call("patch", f"/projects/{self.project_id}/tasks/{task_id}", {"status": status})
        # The same status again is allowed, a different one is refused
        assert response.status_code == (200 if status == self.tasks[task_id] else 409), response.json

    # ----------------------------------------------------------------------------- the lock and the flags

    @rule(value=st.booleans())
    def set_locked(self, value):
        assert self.call("patch", f"/projects/{self.project_id}", {"locked": value}).status_code == 200
        self.locked = value

    @rule(value=st.booleans())
    def set_link_enabled(self, value):  # M4
        was = self.link_active
        response = self.call("patch", self.link_url, {"enabled": value})
        if self.locked and self.drained:
            assert response.status_code == 200, response.json
            self.link_enabled = value
            self.backfill_if_activated(was)
        else:
            assert response.status_code == 409, response.json

    @rule(value=st.booleans())
    def set_link_revoked(self, value):  # M5
        was = self.link_active
        response = self.call("patch", self.link_url, {"revoked": value})
        assert response.status_code == 200, response.json
        self.link_revoked = value
        self.backfill_if_activated(was)

    @rule(value=st.booleans())
    def set_global_enabled(self, value):  # M4, and M6 when it is switched back on
        switched_on = value and not self.global_enabled
        self.tick += 1  # the route reads the clock during the call: the cursor lands after every PR merged so far
        response = self.call("patch", f"/global/repositories/triggers/{self.repo_id}", {"enabled": value})
        if self.locked and self.drained:
            assert response.status_code == 200, response.json
            self.global_enabled = value
            if switched_on:
                self.skip_before = len(self.provider)
        else:
            assert response.status_code == 409, response.json

    # ----------------------------------------------------------------------------- invariants

    @invariant()
    def triggers_match_model(self):
        page = self.call("get", f"{self.link_url}/pull_requests?per_page=200").json
        assert {item["number"]: item["state"] for item in page["items"]} == self.triggers

    @invariant()
    def stored_prs_match_model(self):
        listing = self.call("get", f"/global/repositories/triggers/{self.repo_id}/pull_requests?per_page=200").json
        assert listing["total"] == len(self.stored)

    @invariant()
    def tasks_match_model(self):
        page = self.call("get", f"/projects/{self.project_id}/tasks?per_page=200").json
        assert {task["id"]: task["status"] for task in page["tasks"]} == self.tasks
        links = self.call("get", f"{self.link_url}/pull_requests?per_page=200").json["items"]
        task_ids = [item["task_id"] for item in links if item["task_id"] is not None]
        assert len(task_ids) == len(set(task_ids)), "two triggers share a task"

    @invariant()
    def link_active_matches_model(self):
        assert self.call("get", self.link_url).json["active"] == self.link_active


TriggerLinkMachine.TestCase.settings = settings(
    max_examples=50, stateful_step_count=25, deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
TestTriggerLinkRules = TriggerLinkMachine.TestCase
