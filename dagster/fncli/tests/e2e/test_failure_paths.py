"""
The failure paths of the GlobalResource flow. Same style as the happy path: one test per fncli command or expected state,
in order, on one project, stopping at the first failure with the last snapshot. Each group of tests leaves the project as
the next expects it: links active, tokens restored, everything switched back on.

It starts with an invalid spec, a pull request outside the watched directory, a revoked trigger link, a second project on the
same repository, a lost token and a failing task. Then come the groups that switch something off or withdraw it: a revoked
project, a trigger link switched off, a GlobalResource (the trigger repository) switched off or revoked, a Secret switched
off, and enabling a project with backfill. In each of them a pull request is merged while something is off, and none of them
may get a task. Switching it back on skips the gap, so the pull request still gets no task, unless the project is enabled
with backfill. The last group is work in flight: a results link switched off before delivery (the result is held FAILED and
the delivery retry sensor delivers it once the link is on). The rules are in
../../../../docs/architecture/revoke-and-enabled.md.

Not covered by any e2e suite for now: the scenarios that stop and start sensors were removed, and the reconcile sensor is
expected to make up for sensors being down. Only the webserver and Dagster unit tests cover revoking a result that is already
held, and retrying tasks is not covered (on hold until after beta). These behaviours are therefore not checked end to end (the
rules are in revoke-and-enabled.md, "May a waiting task launch?" and "May a finished task's result be delivered?"):
- restarting the ingest sensor does not duplicate pull requests or tasks, also after a trigger link was revoked and un-revoked;
- a task whose results link's target_dir changes before it launches fails, and its cause names the change
  (the pinned configuration changed);
- sensors that were all stopped while a pull request was merged catch up when started: the pull request gets one trigger
  and one task, and no task stays PENDING;
- a results link revoked after the task succeeded and before its delivery: the result is REVOKED and FAILED, never
  delivered, and un-revoking the link delivers nothing;
- a results link's target_dir changed after the task succeeded and before its delivery: the result is STALE and FAILED, never
  delivered, and restoring the target_dir delivers nothing;
- a dataset link revoked while the task is PENDING: the task fails at launch with a cause that starts "revoked: " and names
  the dataset, and has no result;
- a global dataset switched off while the task is PENDING: the task fails at launch with a cause saying the dataset is not
  active and naming it, and has no result.

The "nothing happens" checks wait a few sensor ticks (5 ticks of the cluster's sensor interval; E2E_FAST_SENSORS=1 sets it to 1 s for the run). The project is cleared at the start of the run, and kept
afterwards unless E2E_TEARDOWN=1.

All sensors must already be running before the run (`fncli start-sensor --sensor all`); the run does not start them.
"""

import json
import os

import pytest

from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.common import DagsterConfig, build_admin_backend_api
from fncli.cmds.pr import (
    commit_gitea_file_command,
    create_gitea_branch_command,
    create_gitea_pr_command,
    merge_gitea_pr_command,
    new_branch_name,
)
from fncli.cmds.project import project_healthcheck_command
from fncli.cmds.secret import (
    delete_gitea_token_command,
    init_git_secret_command,
    verify_git_secret_command,
)
from fncli.cmds.sensor import DELIVERY_RETRY_SENSOR, sensor_status_command
from fncli.cmds.state import (
    global_set_command,
    link_set_command,
    project_set_command,
    second_project_setup_command,
    second_project_teardown_command,
    secret_set_command,
)
from fncli.sensors import DagsterAPI
from fncli.tests.e2e.conftest import (
    QUIET_SENSORS,
    SETUP_IDS,
    TEARDOWN_IDS,
    counts,
    logger,
    pull_requests,
    quiet_wait,
    stored_count,
    summary,
    teardown_step,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_failure]

QUIET_TICKS = 5
TASK_TIMEOUT = int(os.environ.get("E2E_TASK_TIMEOUT", 600))  # a task that fails to start can sit in a pull back-off
STEP_TIMEOUT = 300
# A task that has not finished, and a result that is still being delivered, are work in flight
UNFINISHED_TASK = ["PENDING", "QUEUED", "RUNNING"]
SECOND_PROJECT = "QaTwo"
# Every step a result can end at: a revoked result stays at REVOKED and is never delivered
SETTLED_STEPS = ["OPENED", "MERGED", "CLOSED", "REVOKED", "STALE"]
# The steps of a result that has been delivered
DELIVERED_STEPS = ["OPENED", "MERGED"]


@pytest.fixture(scope="module")
def flow():
    """What the steps hand on to each other: PR numbers and branches by scenario, counts taken before a change."""
    return {}


def create_branch(fncli, flow, key):
    flow[f"{key}_branch"] = new_branch_name()
    fncli.call(create_gitea_branch_command, branch=flow[f"{key}_branch"])


def commit_file(fncli, flow, key, kind):
    fncli.call(commit_gitea_file_command, branch=flow[f"{key}_branch"], kind=kind)


def create_pr(fncli, flow, key, kind):
    flow[f"{key}_pr"] = fncli.call(create_gitea_pr_command, branch=flow[f"{key}_branch"], kind=kind)["number"]


def merge_pr(fncli, flow, key):
    fncli.call(merge_gitea_pr_command, number=flow[f"{key}_pr"], watch=False, timeout=0)


def pr_of(snapshot, flow, key):
    return next((pr for pr in pull_requests(snapshot) if pr["number"] == flow[f"{key}_pr"]), None)


def trigger_link(snapshot):
    return snapshot["trigger_links"][0]


def tasks_finished(snapshot):
    return all(task["status"] not in UNFINISHED_TASK for task in snapshot["tasks"])


def drained(snapshot):
    return tasks_finished(snapshot) and all(r["step"] in SETTLED_STEPS for r in snapshot["results"])


def record_counts(fncli, flow, key):
    flow[key] = counts(fncli.snapshot())
    logger.info(f"{key}: (PRs, tasks) = {flow[key]}")


def grew_by_one(flow, key):
    prs, tasks = flow[key]
    return lambda snapshot: counts(snapshot) == (prs + 1, tasks + 1)


def merge_watched_pr(fncli, flow, key):
    create_branch(fncli, flow, key)
    commit_file(fncli, flow, key, "watched")
    create_pr(fncli, flow, key, "watched")
    merge_pr(fncli, flow, key)


def assert_no_new_task(fncli, flow, key, what):
    """After a few sensor ticks the project still has the tasks it had when the counts were taken."""
    quiet_wait(QUIET_TICKS)
    snapshot = fncli.snapshot()
    assert len(snapshot["tasks"]) == flow[key][1], f"{what}: a task was created\n{json.dumps(summary(snapshot), indent=2)}"


def record_stored(fncli, flow, key):
    """Records the counts and, for the link that gets no trigger, how many pull requests the repository has stored."""
    record_counts(fncli, flow, key)
    flow[f"{key}_stored"] = stored_count(fncli.snapshot())


def stored_without_a_trigger(flow, key):
    """The pull request is stored (+1, read from the repository: the link gets no trigger for it) and has no task."""
    return lambda snapshot: stored_count(snapshot) == flow[f"{key}_stored"] + 1 and counts(snapshot) == flow[key]


def results_of(snapshot, task_id):
    return [r for r in snapshot["results"] if r["task_id"] == task_id]


def task_has_status(flow, key, status):
    """The task of the group once it has the status. Failing at once if it FAILED when something else was waited for."""

    def check(snapshot):
        task = next((t for t in snapshot["tasks"] if t["id"] == flow[key]), None)
        if task and task["status"] == "FAILED" and status != "FAILED":
            pytest.fail(f"task {flow[key]} FAILED while waiting for {status}: {task}")
        return task if task and task["status"] == status else None

    return check


def result_with(flow, key, step, state=None):
    """The task's result once it is at the step (and in the state, when given)."""
    return lambda snapshot: next(
        (r for r in results_of(snapshot, flow[key]) if r["step"] == step and (state is None or r["state"] == state)), None
    )


def merge_pr_with_task(fncli, flow, key):
    """A watched PR merged, its task created: the task id goes to flow[f"{key}_task"]."""
    merge_watched_pr(fncli, flow, key)
    pr = fncli.wait_for_state(f"PR #{flow[f'{key}_pr']} YIELDED with a task_id", STEP_TIMEOUT, yielded_with_task(flow, key))
    flow[f"{key}_task"] = pr["task_id"]


# --- Preflight: the admin login the revoke tests need -----------------------------------------


def test_admin_login(fncli):
    """Revoking is admin only: log in as the first Keycloak user once, here, so a bad login fails with its cause."""
    try:
        build_admin_backend_api(fncli.config).session.adapter.access_token
    except Exception as error:
        pytest.fail(
            "admin login failed: check the first Keycloak user exists and KEYCLOAK_FIRST_USER_EMAIL in .dev.env "
            f"matches the chart ({type(error).__name__}: {error})"
        )


# --- Setup: a fresh project and the sensors running -------------------------------------------


def test_teardown_leftover_second_project(fncli):
    """A run that died mid-test leaves the second project behind, and creating it again fails with "already exists"."""
    if fncli.backend_api.find_project(SECOND_PROJECT) is not None:
        fncli.call(second_project_teardown_command, name=SECOND_PROJECT, expect=204)


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_leftovers(fncli, command, options):
    teardown_step(fncli, command, options)


@pytest.mark.parametrize("command, options", SETUP_STEPS, ids=SETUP_IDS)
def test_setup(fncli, command, options):
    fncli.call(command, **options)


def test_verify_project_after_setup(fncli):
    fncli.run("verify-project")


def test_project_starts_empty(fncli):
    snapshot = fncli.snapshot()
    assert counts(snapshot) == (0, 0), f"expected a project with no PRs or tasks\n{summary(snapshot)}"
    assert trigger_link(snapshot)["active"] is True


# --- an invalid spec is rejected, no task -------------------------------------------------


def test_invalid_spec_record_counts(fncli, flow):
    record_counts(fncli, flow, "invalid_spec_before")

def test_invalid_spec_create_branch(fncli, flow):
    create_branch(fncli, flow, "invalid_spec")


def test_invalid_spec_commit_file(fncli, flow):
    commit_file(fncli, flow, "invalid_spec", "invalid")


def test_invalid_spec_create_pr(fncli, flow):
    create_pr(fncli, flow, "invalid_spec", "invalid")


def test_invalid_spec_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "invalid_spec")


def test_invalid_spec_pr_rejected(fncli, flow):
    def rejected(snapshot):
        pr = pr_of(snapshot, flow, "invalid_spec")
        return pr if pr and pr["state"] == "REJECTED" else None

    flow["invalid_spec_rejected"] = fncli.wait_for_state(f"PR #{flow['invalid_spec_pr']} REJECTED", STEP_TIMEOUT, rejected)


def test_invalid_spec_rejection_has_cause_and_no_task(flow):
    pr = flow["invalid_spec_rejected"]
    assert pr["state_cause"], f"REJECTED without a state_cause: {pr}"
    assert pr["task_id"] is None, f"a rejected PR has a task: {pr}"


def test_invalid_spec_no_task_created(fncli, flow):
    prs, tasks = flow["invalid_spec_before"]
    snapshot = fncli.snapshot()
    assert len(snapshot["tasks"]) == tasks, f"the task count grew\n{summary(snapshot)}"
    assert len(pull_requests(snapshot)) == prs + 1


# --- a PR outside the watched directory creates no trigger ---------------------------------


def test_unwatched_pr_record_counts(fncli, flow):
    record_counts(fncli, flow, "unwatched_pr_before")

def test_unwatched_pr_create_branch(fncli, flow):
    create_branch(fncli, flow, "unwatched_pr")


def test_unwatched_pr_commit_file(fncli, flow):
    commit_file(fncli, flow, "unwatched_pr", "unwatched")


def test_unwatched_pr_create_pr(fncli, flow):
    create_pr(fncli, flow, "unwatched_pr", "unwatched")


def test_unwatched_pr_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "unwatched_pr")


def test_unwatched_pr_nothing_created(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["unwatched_pr_before"], "unwatched PR")


# --- a PR merged while the link is revoked never gets a trigger -------------------------------


def test_revoked_link_record_counts(fncli, flow):
    record_counts(fncli, flow, "revoked_link_before")


def test_revoked_link_revoke_link(fncli):
    fncli.call(link_set_command, kind="trigger", revoked="true", expect=200)


def test_revoked_link_link_inactive(fncli):
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is False)

def test_revoked_link_create_branch(fncli, flow):
    create_branch(fncli, flow, "revoked_link")


def test_revoked_link_commit_file(fncli, flow):
    commit_file(fncli, flow, "revoked_link", "watched")


def test_revoked_link_create_pr(fncli, flow):
    create_pr(fncli, flow, "revoked_link", "watched")


def test_revoked_link_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "revoked_link")


def test_revoked_link_nothing_ingested_while_revoked(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["revoked_link_before"], "revoked link")


def test_revoked_link_unrevoke_link(fncli):
    fncli.call(link_set_command, kind="trigger", revoked="false", expect=200)


def test_revoked_link_missed_pr_not_replayed(fncli, flow):
    """Un-revoking moves the link's cursor to now: the PR merged while revoked is stored but gets no trigger."""
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["revoked_link_before"], "PR merged while the link was revoked, after un-revoking")


# --- a second project on the same repository ---------------------------------------------


def test_second_project_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_second_project_record_counts(fncli, flow):
    record_counts(fncli, flow, "second_project_before")


def test_second_project_second_project_setup(fncli):
    fncli.call(second_project_setup_command, name=SECOND_PROJECT)


def test_second_project_create_branch(fncli, flow):
    create_branch(fncli, flow, "second_project")


def test_second_project_commit_file(fncli, flow):
    commit_file(fncli, flow, "second_project", "watched")


def test_second_project_create_pr(fncli, flow):
    create_pr(fncli, flow, "second_project", "watched")


def test_second_project_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "second_project")


def yielded_with_task(flow, key):
    def check(snapshot):
        pr = pr_of(snapshot, flow, key)
        return pr if pr and pr["state"] == "YIELDED" and pr["task_id"] else None

    return check


def test_second_project_both_projects_get_a_task(fncli, flow):
    flow["second_project_task_one"] = fncli.wait_for_state("the test project's task", STEP_TIMEOUT, yielded_with_task(flow, "second_project"))["task_id"]
    flow["second_project_task_two"] = fncli.wait_for_state(
        f"{SECOND_PROJECT}'s task", STEP_TIMEOUT, yielded_with_task(flow, "second_project"), project=SECOND_PROJECT
    )["task_id"]
    assert flow["second_project_task_one"] != flow["second_project_task_two"], "both projects share one task for the same PR"


def test_second_project_revoke_second_projects_link(fncli):
    fncli.call(link_set_command, kind="trigger", revoked="true", project=SECOND_PROJECT, expect=200)


def test_second_project_wait_for_tasks_to_finish_again(fncli):
    for project in (None, SECOND_PROJECT):
        fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished, project=project)


def test_second_project_record_both_counts(fncli, flow):
    record_counts(fncli, flow, "second_project_variant_before")
    flow["second_project_variant_two_before"] = counts(fncli.snapshot(SECOND_PROJECT))


def test_second_project_create_branch_two(fncli, flow):
    create_branch(fncli, flow, "second_project_variant")


def test_second_project_commit_file_two(fncli, flow):
    commit_file(fncli, flow, "second_project_variant", "watched")


def test_second_project_create_pr_two(fncli, flow):
    create_pr(fncli, flow, "second_project_variant", "watched")


def test_second_project_merge_pr_two(fncli, flow):
    merge_pr(fncli, flow, "second_project_variant")


def test_second_project_only_the_test_project_gets_the_next_pr(fncli, flow):
    fncli.wait_for_state("the test project's next PR with a task (+1 each)", STEP_TIMEOUT, grew_by_one(flow, "second_project_variant_before"))
    quiet_wait(QUIET_TICKS)
    two = counts(fncli.snapshot(SECOND_PROJECT))
    assert two == flow["second_project_variant_two_before"], f"{SECOND_PROJECT} got something through its revoked link: {two}"


def test_second_project_wait_for_tasks_to_finish_before_teardown(fncli):
    for project in (None, SECOND_PROJECT):
        fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, drained, project=project)


def test_second_project_second_project_teardown(fncli):
    fncli.call(second_project_teardown_command, name=SECOND_PROJECT, expect=204)


# --- a lost token fails clearly, then recovers -------------------------------------------


def test_lost_token_wait_for_tasks_to_finish(fncli):
    # Lets the tasks of the earlier scenarios settle before the counts are taken
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_lost_token_delete_trigger_token(fncli):
    fncli.call(delete_gitea_token_command, entity="trigger")


def test_lost_token_record_counts(fncli, flow):
    record_counts(fncli, flow, "lost_token_before")

def test_lost_token_create_branch(fncli, flow):
    create_branch(fncli, flow, "lost_token")


def test_lost_token_commit_file(fncli, flow):
    commit_file(fncli, flow, "lost_token", "watched")


def test_lost_token_create_pr(fncli, flow):
    create_pr(fncli, flow, "lost_token", "watched")


def test_lost_token_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "lost_token")


def test_lost_token_nothing_ingested_without_token(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["lost_token_before"], "trigger token deleted")


def test_lost_token_ingest_shows_an_auth_error(fncli):
    """The ingest sensor fails its tick naming the repository, rather than silently skipping or crashing. The other
    sensors kept ticking: the quiet wait above only returns when ingest, evaluate and launcher all ticked."""
    fncli.call(sensor_status_command)
    ticks = DagsterAPI(DagsterConfig().dagster_url).get_sensor_ticks("git_pull_request_ingest_sensor", QUIET_TICKS + 2)
    def error_text(error: dict) -> str:
        """The tick's error is a wrapper (SensorExecutionError): the sensor's own message is in its stack and causes."""
        causes = " ".join(error_text(cause) for cause in error.get("causes") or [])
        return " ".join([error.get("message") or "", " ".join(error.get("stack") or []), causes])

    texts = [error_text(tick["error"]) for tick in ticks if tick["status"] == "FAILURE" and tick["error"]]
    logger.info(f"ingest ticks after token deletion: {[tick['status'] for tick in ticks]}; errors: {[t[:200] for t in texts[:2]]}")
    assert any("Ingest failed" in text for text in texts), f"no ingest tick failed with the token deleted: {ticks}"


def test_lost_token_healthcheck_fails(fncli):
    assert fncli.exit_code(project_healthcheck_command) != 0, "project-healthcheck exited 0 with the trigger token deleted"


def test_lost_token_init_git_secret(fncli):
    fncli.call(init_git_secret_command, entity="trigger")


def test_lost_token_verify_git_secret(fncli):
    fncli.call(verify_git_secret_command, entity="trigger")


def test_lost_token_pr_processed_after_recovery(fncli, flow):
    fncli.wait_for_state("the missed PR with a trigger and a task (+1 each)", STEP_TIMEOUT, grew_by_one(flow, "lost_token_before"))


def test_lost_token_healthcheck_ok_again(fncli):
    fncli.call(project_healthcheck_command)


# --- a failing task stays failed ---------------------------------------------------------


def test_failing_task_create_branch(fncli, flow):
    create_branch(fncli, flow, "failing_task")


def test_failing_task_commit_file(fncli, flow):
    commit_file(fncli, flow, "failing_task", "failing")  # a valid spec whose task exits non-zero


def test_failing_task_create_pr(fncli, flow):
    create_pr(fncli, flow, "failing_task", "failing")


def test_failing_task_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "failing_task")


def test_failing_task_pr_yielded(fncli, flow):
    def yielded(snapshot):
        pr = pr_of(snapshot, flow, "failing_task")
        return pr if pr and pr["state"] == "YIELDED" and pr["task_id"] else None

    flow["failing_task"] = fncli.wait_for_state(f"PR #{flow['failing_task_pr']} YIELDED with a task_id", STEP_TIMEOUT, yielded)["task_id"]


def test_failing_task_task_failed(fncli, flow):
    def failed(snapshot):
        return next((t for t in snapshot["tasks"] if t["id"] == flow["failing_task"] and t["status"] == "FAILED"), None)

    fncli.wait_for_state(f"task {flow['failing_task']} FAILED", TASK_TIMEOUT, failed)


def test_failing_task_no_result_and_stays_failed(fncli, flow):
    quiet_wait(ticks=12)
    snapshot = fncli.snapshot()
    task = next(t for t in snapshot["tasks"] if t["id"] == flow["failing_task"])
    assert task["status"] == "FAILED", f"the task left FAILED\n{summary(snapshot)}"
    assert not [r for r in snapshot["results"] if r["task_id"] == flow["failing_task"]], f"a failed task has a result\n{summary(snapshot)}"


# --- a PR merged while the project is revoked is stored and gets no task --------------------


def test_revoked_project_wait_for_tasks_to_finish(fncli):
    # The groups below count tasks: the task and result of the earlier groups must be done, or they would show up as new
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, drained)


def test_revoked_project_record_counts(fncli, flow):
    record_stored(fncli, flow, "revoked_project_before")


def test_revoked_project_revoke_project(fncli):
    fncli.call(project_set_command, revoked="true", expect=200)


def test_revoked_project_is_revoked(fncli):
    fncli.wait_for_state("the project revoked", STEP_TIMEOUT, lambda s: s["project"]["revoked"] is True)


def test_revoked_project_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "revoked_project")


def test_revoked_project_pr_stored_without_a_task(fncli, flow):
    fncli.wait_for_state("the PR stored, with no task", STEP_TIMEOUT, stored_without_a_trigger(flow, "revoked_project_before"))
    assert_no_new_task(fncli, flow, "revoked_project_before", "revoked project")


def test_revoked_project_restore_project(fncli):
    fncli.call(project_set_command, revoked="false", expect=200)


def test_revoked_project_missed_pr_not_replayed(fncli, flow):
    """Restoring the project skips the gap: the PR merged while it was revoked still has no task."""
    assert_no_new_task(fncli, flow, "revoked_project_before", "PR merged while the project was revoked, after restoring it")


# --- a PR merged while the trigger link is switched off gets no task ----------------------------


def test_disabled_link_record_counts(fncli, flow):
    record_counts(fncli, flow, "disabled_link_before")


def test_disabled_link_switch_off_link(fncli):
    fncli.call(link_set_command, kind="trigger", enabled="false", expect=200)


def test_disabled_link_link_inactive(fncli):
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is False)


def test_disabled_link_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "disabled_link")


def test_disabled_link_nothing_ingested_while_off(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["disabled_link_before"], "trigger link switched off")


def test_disabled_link_switch_on_link(fncli):
    fncli.call(link_set_command, kind="trigger", enabled="true", expect=200)


def test_disabled_link_missed_pr_not_replayed(fncli, flow):
    assert_no_new_task(fncli, flow, "disabled_link_before", "PR merged while the trigger link was off, after switching it on")


# --- a PR merged while the GlobalResource is switched off gets no task ------------------------


def test_disabled_global_record_counts(fncli, flow):
    record_counts(fncli, flow, "disabled_global_before")


def test_disabled_global_switch_off_global(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="false", expect=200)


def test_disabled_global_link_inactive(fncli):
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is False)


def test_disabled_global_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "disabled_global")


def test_disabled_global_nothing_ingested_while_off(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["disabled_global_before"], "GlobalResource switched off")


def test_disabled_global_switch_on_global(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="true", expect=200)


def test_disabled_global_link_active_again(fncli):
    fncli.wait_for_state("the trigger link active", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is True)


def test_disabled_global_missed_pr_not_replayed(fncli, flow):
    """Catching up stores the PR merged while the GlobalResource was off, and it gets no task."""
    assert_no_new_task(fncli, flow, "disabled_global_before", "PR merged while the GlobalResource was off, after switching it on")


# --- a PR merged while the GlobalResource is revoked gets no task -----------------------------


def test_revoked_global_record_counts(fncli, flow):
    record_counts(fncli, flow, "revoked_global_before")


def test_revoked_global_revoke_global(fncli):
    fncli.call(global_set_command, kind="trigger", revoked="true", expect=200)


def test_revoked_global_link_inactive(fncli):
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is False)


def test_revoked_global_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "revoked_global")


def test_revoked_global_nothing_ingested_while_revoked(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["revoked_global_before"], "GlobalResource revoked")


def test_revoked_global_restore_global(fncli):
    fncli.call(global_set_command, kind="trigger", revoked="false", expect=200)


def test_revoked_global_link_active_again(fncli):
    fncli.wait_for_state("the trigger link active", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is True)


def test_revoked_global_missed_pr_not_replayed(fncli, flow):
    assert_no_new_task(fncli, flow, "revoked_global_before", "PR merged while the GlobalResource was revoked, after restoring it")


# --- a PR merged while the trigger repository's Secret is switched off gets no task -----------


def test_disabled_secret_record_counts(fncli, flow):
    record_counts(fncli, flow, "disabled_secret_before")


def test_disabled_secret_switch_off_secret(fncli):
    fncli.call(secret_set_command, entity="trigger", enabled="false", expect=200)


def test_disabled_secret_switches_off_the_repository(fncli):
    """Switching a Secret off switches off every repository that uses it."""
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is False)


def test_disabled_secret_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "disabled_secret")


def test_disabled_secret_nothing_ingested_while_off(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["disabled_secret_before"], "Secret switched off")


def test_disabled_secret_switch_on_secret(fncli):
    fncli.call(secret_set_command, entity="trigger", enabled="true", expect=200)


def test_disabled_secret_repository_stays_off(fncli):
    """Switching the Secret on changes only the Secret: the repository stays off until it is switched on itself."""
    assert trigger_link(fncli.snapshot())["active"] is False


def test_disabled_secret_switch_on_repository(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="true", expect=200)


def test_disabled_secret_link_active_again(fncli):
    fncli.wait_for_state("the trigger link active", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is True)


def test_disabled_secret_missed_pr_not_replayed(fncli, flow):
    assert_no_new_task(fncli, flow, "disabled_secret_before", "PR merged while the Secret was off, after switching it back on")


# --- a PR merged while the project is disabled gets a task when it is enabled with backfill ----


def test_backfill_record_counts(fncli, flow):
    record_stored(fncli, flow, "backfill_before")


def test_backfill_disable_project(fncli):
    fncli.call(project_set_command, enabled="false", expect=200)


def test_backfill_project_is_disabled(fncli):
    fncli.wait_for_state("the project disabled", STEP_TIMEOUT, lambda s: s["project"]["enabled"] is False)


def test_backfill_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "backfill")


def test_backfill_pr_stored_without_a_task(fncli, flow):
    fncli.wait_for_state("the PR stored, with no task", STEP_TIMEOUT, stored_without_a_trigger(flow, "backfill_before"))


def test_backfill_enable_project_with_backfill(fncli):
    fncli.call(project_set_command, enabled="true", backfill=True, expect=200)


def test_backfill_pr_gets_its_task(fncli, flow):
    prs, tasks = flow["backfill_before"]
    fncli.wait_for_state("the stored PR with a task (+1 each)", TASK_TIMEOUT, lambda s: counts(s) == (prs + 1, tasks + 1))


def test_backfill_task_finishes(fncli):
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


# --- work in flight: a results link switched off before delivery is held FAILED, delivered once the link is on ----------------


def test_switched_off_results_link_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, drained)


def test_switched_off_results_link_switch_off_link(fncli):
    fncli.call(link_set_command, kind="results", enabled="false", expect=200)


def test_switched_off_results_link_link_inactive(fncli):
    fncli.wait_for_state("the results link inactive", STEP_TIMEOUT, lambda s: s["results_links"][0]["active"] is False)


def test_switched_off_results_link_merge_pr(fncli, flow):
    """A switched off results link does not stop the task: it launches and runs."""
    merge_pr_with_task(fncli, flow, "switched_off_results_link")


def test_switched_off_results_link_task_succeeds(fncli, flow):
    fncli.wait_for_state("the task SUCCESS", TASK_TIMEOUT, task_has_status(flow, "switched_off_results_link_task", "SUCCESS"))


def test_switched_off_results_link_result_is_held_failed(fncli, flow):
    """Recorded by the backend at step UNKNOWN, state FAILED ("results link switched off"): not final, nothing pushed."""
    fncli.wait_for_state("the result FAILED, held", TASK_TIMEOUT, result_with(flow, "switched_off_results_link_task", "UNKNOWN", "FAILED"))


def test_switched_off_results_link_not_delivered_while_off(fncli, flow):
    """The retry sensor lists only the results whose link is active, so the result stays held."""
    quiet_wait(QUIET_TICKS, [*QUIET_SENSORS, DELIVERY_RETRY_SENSOR])
    snapshot = fncli.snapshot()
    results = results_of(snapshot, flow["switched_off_results_link_task"])
    assert [(r["step"], r["state"]) for r in results] == [("UNKNOWN", "FAILED")], f"unexpected results\n{json.dumps(summary(snapshot), indent=2)}"


def test_switched_off_results_link_switch_on_link(fncli):
    fncli.call(link_set_command, kind="results", enabled="true", expect=200)


def test_switched_off_results_link_retry_sensor_delivers(fncli, flow):
    def delivered(snapshot):
        return next(
            (r for r in results_of(snapshot, flow["switched_off_results_link_task"]) if r["state"] == "DELIVERED" and r["step"] in DELIVERED_STEPS), None
        )

    result = fncli.wait_for_state("the held result DELIVERED by the retry sensor", TASK_TIMEOUT, delivered)
    assert result["number"] and result["url"], f"delivered without a results PR: {result}"


# --- Teardown ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, final=True)
