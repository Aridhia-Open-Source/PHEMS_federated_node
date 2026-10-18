"""
The failure paths of the global-resources flow, from project/handover/e2e-qa-plan.md. Same style as
the happy path: one test per fncli command or expected state, in order, on one project, stopping at
the first failure with the last snapshot. The scenarios run in the plan's order and each leaves the
project as the next expects it: links active, tokens restored.

Not here: S7, S8, S9 and S16 (the lock and drained rules, a disabled global repository, the results link revoked
mid-task). They depend on the lock and on catching a task in flight, and are covered by the webserver and Dagster
unit tests. S14 is the teardown and the setup at the two ends; S15 (known gaps) is not automated.

The "nothing happens" checks wait a few sensor ticks (5 ticks of the 1 s interval the suite sets; E2E_KEEP_INTERVAL=1 leaves the cluster's own). The project is cleared at the start of the run, and kept
afterwards unless E2E_TEARDOWN=1.
"""

import os
import time

import pytest

from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.common import DagsterConfig
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
from fncli.cmds.sensor import (
    ALL_SENSORS,
    sensor_status_command,
    start_sensor_command,
    stop_sensor_command,
)
from fncli.cmds.state import (
    link_set_command,
    second_project_setup_command,
    second_project_teardown_command,
)
from fncli.sensors import DagsterAPI
from fncli.tests.e2e.conftest import (
    SETUP_IDS,
    TEARDOWN_IDS,
    counts,
    logger,
    pull_requests,
    quiet_wait,
    set_sensor_interval,
    start_sensor,
    summary,
    teardown_step,
    tick_seconds,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_failure]

SENSOR_INTERVAL = 1  # seconds: the "nothing happens" checks then take QUIET_TICKS of these
QUIET_TICKS = 5
TASK_TIMEOUT = int(os.environ.get("E2E_TASK_TIMEOUT", 600))  # a task that fails to start can sit in a pull back-off
STEP_TIMEOUT = 300
# A task that has not finished, and a result that is still being delivered, block lock-gated changes
UNFINISHED_TASK = ["PENDING", "QUEUED", "RUNNING"]
SECOND_PROJECT = "QaTwo"
DELIVERED = ["OPENED", "MERGED"]


@pytest.fixture(scope="module", autouse=True)
def fast_sensors(request):
    """Run the suite with a 1 s sensor interval, and put the cluster's interval back afterwards, even when a test failed.

    Skipped when E2E_KEEP_INTERVAL=1. The code server restarts both times, which stops the sensors: test_start_sensor
    starts them again after setup, and the restore leaves them stopped, as a fresh install does.
    """
    if os.environ.get("E2E_KEEP_INTERVAL") == "1":
        yield
        return
    previous = set_sensor_interval(SENSOR_INTERVAL)

    def restore():
        if previous is not None:
            set_sensor_interval(int(previous))

    request.addfinalizer(restore)
    yield


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
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["s4_before"], "unwatched PR")


# --- S5: restarting ingest does not duplicate ---------------------------------------------------


def test_s5_record_counts(fncli, flow):
    record_counts(fncli, flow, "s5_before")


def test_s5_stop_ingest(fncli):
    fncli.call(stop_sensor_command, sensor="ingest")


def test_s5_start_ingest(fncli):
    fncli.call(start_sensor_command, sensor="ingest")


def test_s5_counts_unchanged(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["s5_before"], "ingest restarted")


# --- S6: a PR merged while the link is revoked never gets a trigger -------------------------------


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
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["s6_before"], "revoked link")


def test_s6_unrevoke_link(fncli):
    fncli.call(link_set_command, kind="trigger", revoked="false", expect=200)


def test_s6_missed_pr_not_replayed(fncli, flow):
    """Un-revoking moves the link's cursor to now: the PR merged while revoked is stored but gets no trigger."""
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["s6_before"], "PR merged while the link was revoked, after un-revoking")


# --- S5 again, as the plan asks, after S6 -------------------------------------------------


def test_s5b_record_counts(fncli, flow):
    record_counts(fncli, flow, "s5b_before")


def test_s5b_stop_ingest(fncli):
    fncli.call(stop_sensor_command, sensor="ingest")


def test_s5b_start_ingest(fncli):
    fncli.call(start_sensor_command, sensor="ingest")


def test_s5b_counts_unchanged(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["s5b_before"], "ingest restarted after S6")


# --- S10: a second project on the same repository ---------------------------------------------


def test_s10_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_s10_record_counts(fncli, flow):
    record_counts(fncli, flow, "s10_before")


def test_s10_second_project_setup(fncli):
    fncli.call(second_project_setup_command, name=SECOND_PROJECT)


def test_s10_create_branch(fncli, flow):
    create_branch(fncli, flow, "s10")


def test_s10_commit_file(fncli, flow):
    commit_file(fncli, flow, "s10", "watched")


def test_s10_create_pr(fncli, flow):
    create_pr(fncli, flow, "s10", "watched")


def test_s10_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s10")


def yielded_with_task(flow, key):
    def check(snapshot):
        pr = pr_of(snapshot, flow, key)
        return pr if pr and pr["state"] == "YIELDED" and pr["task_id"] else None

    return check


def test_s10_both_projects_get_a_task(fncli, flow):
    flow["s10_task_one"] = fncli.wait_for_state("the test project's task", STEP_TIMEOUT, yielded_with_task(flow, "s10"))["task_id"]
    flow["s10_task_two"] = fncli.wait_for_state(
        f"{SECOND_PROJECT}'s task", STEP_TIMEOUT, yielded_with_task(flow, "s10"), project=SECOND_PROJECT
    )["task_id"]
    assert flow["s10_task_one"] != flow["s10_task_two"], "both projects share one task for the same PR"


def test_s10_revoke_second_projects_link(fncli):
    fncli.call(link_set_command, kind="trigger", revoked="true", project=SECOND_PROJECT, expect=200)


def test_s10_wait_for_tasks_to_finish_again(fncli):
    for project in (None, SECOND_PROJECT):
        fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished, project=project)


def test_s10_record_both_counts(fncli, flow):
    record_counts(fncli, flow, "s10b_before")
    flow["s10b_two_before"] = counts(fncli.snapshot(SECOND_PROJECT))


def test_s10_create_branch_two(fncli, flow):
    create_branch(fncli, flow, "s10b")


def test_s10_commit_file_two(fncli, flow):
    commit_file(fncli, flow, "s10b", "watched")


def test_s10_create_pr_two(fncli, flow):
    create_pr(fncli, flow, "s10b", "watched")


def test_s10_merge_pr_two(fncli, flow):
    merge_pr(fncli, flow, "s10b")


def test_s10_only_the_test_project_gets_the_next_pr(fncli, flow):
    fncli.wait_for_state("the test project's next PR with a task (+1 each)", STEP_TIMEOUT, grew_by_one(flow, "s10b_before"))
    quiet_wait(QUIET_TICKS)
    two = counts(fncli.snapshot(SECOND_PROJECT))
    assert two == flow["s10b_two_before"], f"{SECOND_PROJECT} got something through its revoked link: {two}"


def test_s10_wait_for_tasks_to_finish_before_teardown(fncli):
    for project in (None, SECOND_PROJECT):
        fncli.wait_for_state("no task in flight and every result delivered", TASK_TIMEOUT, drained, project=project)


def test_s10_second_project_teardown(fncli):
    fncli.call(second_project_teardown_command, name=SECOND_PROJECT, expect=204)


# --- S11: a lost token fails clearly, then recovers -------------------------------------------


def test_s11_wait_for_tasks_to_finish(fncli):
    # Lets the tasks of the earlier scenarios settle before the counts are taken
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
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["s11_before"], "trigger token deleted")


def test_s11_ingest_shows_an_auth_error(fncli):
    """The ingest sensor fails its tick naming the repository, rather than silently skipping or crashing. The other
    sensors kept ticking: the quiet wait above only returns when ingest, evaluate and launcher all ticked."""
    fncli.call(sensor_status_command)
    ticks = DagsterAPI(DagsterConfig().dagster_url).get_sensor_ticks("git_pull_request_ingest_sensor", QUIET_TICKS + 2)
    messages = [(tick["error"] or {}).get("message", "") for tick in ticks if tick["status"] == "FAILURE"]
    logger.info(f"S11 ingest ticks: {[tick['status'] for tick in ticks]}; errors: {messages[:2]}")
    assert any("Ingest failed" in message for message in messages), f"no ingest tick failed with the token deleted: {ticks}"


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


def test_s12_commit_file(fncli, flow):
    commit_file(fncli, flow, "s12", "failing")  # a valid spec whose task exits non-zero


def test_s12_create_pr(fncli, flow):
    create_pr(fncli, flow, "s12", "failing")


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


# --- S17: the results link's target_dir changes before the task launches: the task fails ---------


def test_s17_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_s17_stop_launcher(fncli):
    fncli.call(stop_sensor_command, sensor="launcher")


def test_s17_create_branch(fncli, flow):
    create_branch(fncli, flow, "s17")


def test_s17_commit_file(fncli, flow):
    commit_file(fncli, flow, "s17", "watched")


def test_s17_create_pr(fncli, flow):
    create_pr(fncli, flow, "s17", "watched")


def test_s17_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s17")


def test_s17_task_is_created_and_waits_unlaunched(fncli, flow):
    flow["s17_task"] = fncli.wait_for_state("S17's task", STEP_TIMEOUT, yielded_with_task(flow, "s17"))["task_id"]
    fncli.wait_for_state(
        "S17's task PENDING",
        STEP_TIMEOUT,
        lambda s: any(t["id"] == flow["s17_task"] and t["status"] == "PENDING" for t in s["tasks"]),
    )


def test_s17_change_the_target_dir(fncli, flow):
    flow["s17_original_dir"] = fncli.snapshot()["results_links"][0]["target_dir"]
    fncli.call(link_set_command, kind="results", target_dir="changed-by-s17/", expect=200)  # no lock needed any more


def test_s17_start_launcher(fncli):
    fncli.call(start_sensor_command, sensor="launcher")


def test_s17_task_fails_naming_the_change(fncli, flow):
    task = fncli.wait_for_state(
        "S17's task FAILED",
        TASK_TIMEOUT,
        lambda s: next((t for t in s["tasks"] if t["id"] == flow["s17_task"] and t["status"] == "FAILED"), None),
    )
    cause = task.get("state_cause") or ""
    assert "configuration changed" in cause and "target_dir" in cause, f"unexpected cause: {cause!r}"
    assert not [r for r in fncli.snapshot()["results"] if r["task_id"] == flow["s17_task"]], "a stale task has a result"


def test_s17_restore_the_target_dir(fncli, flow):
    fncli.call(link_set_command, kind="results", target_dir=flow["s17_original_dir"], expect=200)


# --- S13: sensors stopped, a PR merged, sensors started again -----------------------------------


def test_s13_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_s13_record_counts(fncli, flow):
    record_counts(fncli, flow, "s13_before")


def test_s13_stop_all_sensors(fncli):
    fncli.call(stop_sensor_command, sensor="all")


def test_s13_create_branch(fncli, flow):
    create_branch(fncli, flow, "s13")


def test_s13_commit_file(fncli, flow):
    commit_file(fncli, flow, "s13", "watched")


def test_s13_create_pr(fncli, flow):
    create_pr(fncli, flow, "s13", "watched")


def test_s13_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "s13")


def test_s13_nothing_happens_while_stopped(fncli, flow):
    time.sleep(max(10, QUIET_TICKS * tick_seconds()))  # no ticks to count: the sensors are off
    fncli.assert_counts(flow["s13_before"], "all sensors stopped")


@pytest.mark.parametrize("sensor", ALL_SENSORS)  # in start order: the run-status sensors before the launcher
def test_s13_start_sensor(sensor):
    start_sensor(sensor)


def test_s13_pr_processed_and_no_task_left_pending(fncli, flow):
    fncli.wait_for_state(
        "the PR with a task (+1 each), and no task PENDING",
        TASK_TIMEOUT,
        lambda s: grew_by_one(flow, "s13_before")(s) and all(t["status"] != "PENDING" for t in s["tasks"]),
    )


# --- Teardown ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, final=True)
