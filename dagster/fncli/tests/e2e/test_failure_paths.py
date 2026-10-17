"""
The failure paths of the global-resources flow, from project/handover/e2e-qa-plan.md. Same style as
the happy path: one test per fncli command or expected state, in order, on one project, stopping at
the first failure with the last snapshot. The scenarios run in the plan's order and each leaves the
project as the next expects it: unlocked, links active, tokens restored.

TODO, not covered yet: S8 (a task in flight blocks lock-gated changes: timing dependent), S10 (a
second project on the same repository) and S13 (sensors restarted mid-flow).

The "nothing happens" checks wait a few sensor ticks (DAGSTER_SENSORS_MIN_INTERVAL_SECONDS, default 10).
"""

import pytest

from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.pr import (
    commit_gitea_file_command,
    create_gitea_branch_command,
    create_gitea_pr_command,
    merge_gitea_pr_command,
    new_branch_name,
)
from fncli.cmds.project import project_healthcheck_command
from fncli.cmds.secret import delete_gitea_token_command, init_git_secret_command, verify_git_secret_command
from fncli.cmds.sensor import ALL_SENSORS, sensor_status_command, start_sensor_command, stop_sensor_command
from fncli.cmds.state import global_set_command, link_set_command, project_set_command
from fncli.tests.e2e.conftest import (
    SETUP_IDS,
    TEARDOWN_IDS,
    counts,
    logger,
    pull_requests,
    quiet_wait,
    start_sensor,
    summary,
    teardown_step,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_failure]

TASK_TIMEOUT = 600
STEP_TIMEOUT = 300
# A task that has not finished, and a result that is still being delivered, block lock-gated changes
UNFINISHED_TASK = ["PENDING", "QUEUED", "RUNNING"]
DELIVERED = ["OPENED", "MERGED"]


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
    return tasks_finished(snapshot) and all(r["step"] in DELIVERED for r in snapshot["results"])


def record_counts(fncli, flow, key):
    flow[key] = counts(fncli.snapshot())
    logger.info(f"{key}: (PRs, tasks) = {flow[key]}")


def grew_by_one(flow, key):
    prs, tasks = flow[key]
    return lambda snapshot: counts(snapshot) == (prs + 1, tasks + 1)


# --- Setup: a fresh project and the sensors running -------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_leftovers(fncli, command, options):
    teardown_step(fncli, command, options)


@pytest.mark.parametrize("command, options", SETUP_STEPS, ids=SETUP_IDS)
def test_setup(fncli, command, options):
    fncli.call(command, **options)


def test_verify_project_after_setup(fncli):
    fncli.run("verify-project")


@pytest.mark.parametrize("sensor", ALL_SENSORS)
def test_start_sensor(sensor):
    start_sensor(sensor)


def test_project_starts_empty(fncli):
    snapshot = fncli.snapshot()
    assert counts(snapshot) == (0, 0), f"expected a project with no PRs or tasks\n{summary(snapshot)}"
    assert trigger_link(snapshot)["active"] is True


# --- S3: an invalid spec is rejected, no task -------------------------------------------------


def test_s3_record_counts(fncli, flow):
    record_counts(fncli, flow, "s3_before")

def test_s3_create_branch(fncli, flow):
    create_branch(fncli, flow, "s3")


def test_s3_commit_file(fncli, flow):
    commit_file(fncli, flow, "s3", "invalid")


def test_s3_create_pr(fncli, flow):
    create_pr(fncli, flow, "s3", "invalid")


def test_s3_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s3")


def test_s3_pr_rejected(fncli, flow):
    def rejected(snapshot):
        pr = pr_of(snapshot, flow, "s3")
        return pr if pr and pr["state"] == "REJECTED" else None

    flow["s3_rejected"] = fncli.wait_for_state(f"PR #{flow['s3_pr']} REJECTED", STEP_TIMEOUT, rejected)


def test_s3_rejection_has_cause_and_no_task(flow):
    pr = flow["s3_rejected"]
    assert pr["state_cause"], f"REJECTED without a state_cause: {pr}"
    assert pr["task_id"] is None, f"a rejected PR has a task: {pr}"


def test_s3_no_task_created(fncli, flow):
    prs, tasks = flow["s3_before"]
    snapshot = fncli.snapshot()
    assert len(snapshot["tasks"]) == tasks, f"the task count grew\n{summary(snapshot)}"
    assert len(pull_requests(snapshot)) == prs + 1


# --- S4: a PR outside the watched directory creates no trigger ---------------------------------


def test_s4_record_counts(fncli, flow):
    record_counts(fncli, flow, "s4_before")

def test_s4_create_branch(fncli, flow):
    create_branch(fncli, flow, "s4")


def test_s4_commit_file(fncli, flow):
    commit_file(fncli, flow, "s4", "unwatched")


def test_s4_create_pr(fncli, flow):
    create_pr(fncli, flow, "s4", "unwatched")


def test_s4_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s4")


def test_s4_nothing_created(fncli, flow):
    quiet_wait()
    fncli.assert_counts(flow["s4_before"], "unwatched PR")


# --- S5: restarting ingest does not duplicate ---------------------------------------------------


def test_s5_record_counts(fncli, flow):
    record_counts(fncli, flow, "s5_before")


def test_s5_stop_ingest(fncli):
    fncli.call(stop_sensor_command, sensor="ingest")


def test_s5_start_ingest(fncli):
    fncli.call(start_sensor_command, sensor="ingest")


def test_s5_counts_unchanged(fncli, flow):
    quiet_wait()
    fncli.assert_counts(flow["s5_before"], "ingest restarted")


# --- S6: a revoked link ingests nothing, then backfills -----------------------------------------


def test_s6_record_counts(fncli, flow):
    record_counts(fncli, flow, "s6_before")


def test_s6_revoke_link(fncli):
    fncli.call(link_set_command, kind="trigger", revoked="true", expect=200)


def test_s6_link_inactive(fncli):
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: trigger_link(s)["active"] is False)

def test_s6_create_branch(fncli, flow):
    create_branch(fncli, flow, "s6")


def test_s6_commit_file(fncli, flow):
    commit_file(fncli, flow, "s6", "watched")


def test_s6_create_pr(fncli, flow):
    create_pr(fncli, flow, "s6", "watched")


def test_s6_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s6")


def test_s6_nothing_ingested_while_revoked(fncli, flow):
    quiet_wait()
    fncli.assert_counts(flow["s6_before"], "revoked link")


def test_s6_unrevoke_link(fncli):
    fncli.call(link_set_command, kind="trigger", revoked="false", expect=200)


def test_s6_missed_pr_backfilled(fncli, flow):
    fncli.wait_for_state("the missed PR with a trigger and a task (+1 each)", STEP_TIMEOUT, grew_by_one(flow, "s6_before"))


# --- S7: a disabled link needs the lock, then behaves like a revoked one -----------------------


def test_s7_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_s7_disable_unlocked_refused(fncli):
    fncli.call(link_set_command, kind="trigger", enabled="false", expect=409)


def test_s7_lock_project(fncli):
    fncli.call(project_set_command, locked="true", expect=200)


def test_s7_disable_link(fncli):
    fncli.call(link_set_command, kind="trigger", enabled="false", expect=200)


def test_s7_record_counts(fncli, flow):
    record_counts(fncli, flow, "s7_before")

def test_s7_create_branch(fncli, flow):
    create_branch(fncli, flow, "s7")


def test_s7_commit_file(fncli, flow):
    commit_file(fncli, flow, "s7", "watched")


def test_s7_create_pr(fncli, flow):
    create_pr(fncli, flow, "s7", "watched")


def test_s7_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s7")


def test_s7_nothing_ingested_while_disabled(fncli, flow):
    quiet_wait()
    fncli.assert_counts(flow["s7_before"], "disabled link")


def test_s7_enable_link(fncli):
    fncli.call(link_set_command, kind="trigger", enabled="true", expect=200)


def test_s7_unlock_project(fncli):
    fncli.call(project_set_command, locked="false", expect=200)


def test_s7_missed_pr_picked_up(fncli, flow):
    fncli.wait_for_state("the missed PR with a trigger and a task (+1 each)", STEP_TIMEOUT, grew_by_one(flow, "s7_before"))


# --- S5 again, as the plan asks, after S6 and S7 -------------------------------------------------


def test_s5b_record_counts(fncli, flow):
    record_counts(fncli, flow, "s5b_before")


def test_s5b_stop_ingest(fncli):
    fncli.call(stop_sensor_command, sensor="ingest")


def test_s5b_start_ingest(fncli):
    fncli.call(start_sensor_command, sensor="ingest")


def test_s5b_counts_unchanged(fncli, flow):
    quiet_wait()
    fncli.assert_counts(flow["s5b_before"], "ingest restarted after S6 and S7")


# --- S9: a disabled global repository stops its ingest ------------------------------------------


def test_s9_wait_for_drained(fncli):
    fncli.wait_for_state("no task in flight and every result OPENED or MERGED", TASK_TIMEOUT, drained)


def test_s9_lock_project(fncli):
    fncli.call(project_set_command, locked="true", expect=200)


def test_s9_disable_global_repo(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="false", expect=200)


def test_s9_record_counts(fncli, flow):
    record_counts(fncli, flow, "s9_before")

def test_s9_create_branch(fncli, flow):
    create_branch(fncli, flow, "s9")


def test_s9_commit_file(fncli, flow):
    commit_file(fncli, flow, "s9", "watched")


def test_s9_create_pr(fncli, flow):
    create_pr(fncli, flow, "s9", "watched")


def test_s9_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s9")


def test_s9_nothing_ingested_while_global_disabled(fncli, flow):
    quiet_wait()
    fncli.assert_counts(flow["s9_before"], "global repository disabled")


def test_s9_enable_global_repo(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="true", expect=200)


def test_s9_unlock_project(fncli):
    fncli.call(project_set_command, locked="false", expect=200)


def test_s9_record_gap_pr(fncli, flow):
    """Informational, not asserted: is the PR merged while the repository was off ingested once it is back on?"""
    quiet_wait(ticks=9)
    snapshot = fncli.snapshot()
    logger.info(f"S9 gap PR #{flow['s9_pr']} after re-enabling: {pr_of(snapshot, flow, 's9')}")
    logger.info(f"S9 (PRs, tasks) {flow['s9_before']} -> {counts(snapshot)}")


# --- S11: a lost token fails clearly, then recovers -------------------------------------------


def test_s11_wait_for_tasks_to_finish(fncli):
    # Also lets a task of S9's gap PR, if it was ingested, settle before the counts are taken
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_s11_delete_trigger_token(fncli):
    fncli.call(delete_gitea_token_command, entity="trigger")


def test_s11_record_counts(fncli, flow):
    record_counts(fncli, flow, "s11_before")

def test_s11_create_branch(fncli, flow):
    create_branch(fncli, flow, "s11")


def test_s11_commit_file(fncli, flow):
    commit_file(fncli, flow, "s11", "watched")


def test_s11_create_pr(fncli, flow):
    create_pr(fncli, flow, "s11", "watched")


def test_s11_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s11")


def test_s11_nothing_ingested_without_token(fncli, flow):
    quiet_wait()
    fncli.assert_counts(flow["s11_before"], "trigger token deleted")


def test_s11_sensor_status(fncli):
    # The ingest sensor should show an auth error, not a crash loop. Recorded in the log, not asserted
    fncli.call(sensor_status_command)


def test_s11_healthcheck_fails(fncli):
    assert fncli.exit_code(project_healthcheck_command) != 0, "project-healthcheck exited 0 with the trigger token deleted"


def test_s11_init_git_secret(fncli):
    fncli.call(init_git_secret_command, entity="trigger")


def test_s11_verify_git_secret(fncli):
    fncli.call(verify_git_secret_command, entity="trigger")


def test_s11_pr_processed_after_recovery(fncli, flow):
    fncli.wait_for_state("the missed PR with a trigger and a task (+1 each)", STEP_TIMEOUT, grew_by_one(flow, "s11_before"))


def test_s11_healthcheck_ok_again(fncli):
    fncli.call(project_healthcheck_command)


# --- S12: a failing task stays failed ---------------------------------------------------------


def test_s12_create_branch(fncli, flow):
    create_branch(fncli, flow, "s12")


def test_s12_commit_file(fncli, flow, monkeypatch):
    monkeypatch.setenv("TEST_PR_IMAGE", "does-not-exist:latest")
    commit_file(fncli, flow, "s12", "watched")


def test_s12_create_pr(fncli, flow):
    create_pr(fncli, flow, "s12", "watched")


def test_s12_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s12")


def test_s12_pr_yielded(fncli, flow):
    def yielded(snapshot):
        pr = pr_of(snapshot, flow, "s12")
        return pr if pr and pr["state"] == "YIELDED" and pr["task_id"] else None

    flow["s12_task"] = fncli.wait_for_state(f"PR #{flow['s12_pr']} YIELDED with a task_id", STEP_TIMEOUT, yielded)["task_id"]


def test_s12_task_failed(fncli, flow):
    def failed(snapshot):
        return next((t for t in snapshot["tasks"] if t["id"] == flow["s12_task"] and t["status"] == "FAILED"), None)

    fncli.wait_for_state(f"task {flow['s12_task']} FAILED", TASK_TIMEOUT, failed)


def test_s12_no_result_and_stays_failed(fncli, flow):
    quiet_wait(ticks=12)
    snapshot = fncli.snapshot()
    task = next(t for t in snapshot["tasks"] if t["id"] == flow["s12_task"])
    assert task["status"] == "FAILED", f"the task left FAILED\n{summary(snapshot)}"
    assert not [r for r in snapshot["results"] if r["task_id"] == flow["s12_task"]], f"a failed task has a result\n{summary(snapshot)}"


# --- Teardown ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, keep=True)
