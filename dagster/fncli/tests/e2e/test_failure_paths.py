"""
The failure paths of the GlobalResource flow. Same style as the happy path: one test per fncli command or
expected state, in order, on one project, stopping at the first failure with the last snapshot. Each group of
tests leaves the project as the next expects it: links active, tokens restored.

Not covered here, only by the webserver and Dagster unit tests: switching a trigger link or a GlobalResource
off, a revoked project or results link, revoking a result that is already held, disabling a Secret, and
enabling a project with backfill. The rules are in ../../../../docs/architecture/revoke-and-enabled.md.

The "nothing happens" checks wait a few sensor ticks (5 ticks of the 1 s interval the suite sets; E2E_KEEP_INTERVAL=1 leaves the cluster's own). The project is cleared at the start of the run, and kept
afterwards unless E2E_TEARDOWN=1.
"""

import os
import time

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
    start_sensor,
    summary,
    teardown_step,
    tick_seconds,
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


@pytest.mark.parametrize("sensor", ALL_SENSORS)
def test_start_sensor(sensor):
    start_sensor(sensor)


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


# --- restarting ingest does not duplicate ---------------------------------------------------


def test_idempotent_ingest_record_counts(fncli, flow):
    record_counts(fncli, flow, "idempotent_ingest_before")


def test_idempotent_ingest_stop_ingest(fncli):
    fncli.call(stop_sensor_command, sensor="ingest")


def test_idempotent_ingest_start_ingest(fncli):
    fncli.call(start_sensor_command, sensor="ingest")


def test_idempotent_ingest_counts_unchanged(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["idempotent_ingest_before"], "ingest restarted")


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


# --- idempotency check again after revocation recovery -------------------------------------------------


def test_idempotent_after_revoke_record_counts(fncli, flow):
    record_counts(fncli, flow, "idempotent_after_revoke_before")


def test_idempotent_after_revoke_stop_ingest(fncli):
    fncli.call(stop_sensor_command, sensor="ingest")


def test_idempotent_after_revoke_start_ingest(fncli):
    fncli.call(start_sensor_command, sensor="ingest")


def test_idempotent_after_revoke_counts_unchanged(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["idempotent_after_revoke_before"], "ingest restarted after the trigger link was un-revoked")


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

    fncli.wait_for_state(f"task {flow['failing_task_task']} FAILED", TASK_TIMEOUT, failed)


def test_failing_task_no_result_and_stays_failed(fncli, flow):
    quiet_wait(ticks=12)
    snapshot = fncli.snapshot()
    task = next(t for t in snapshot["tasks"] if t["id"] == flow["failing_task"])
    assert task["status"] == "FAILED", f"the task left FAILED\n{summary(snapshot)}"
    assert not [r for r in snapshot["results"] if r["task_id"] == flow["failing_task"]], f"a failed task has a result\n{summary(snapshot)}"


# --- the results link's target_dir changes before the task launches: the task fails ---------


def test_target_dir_change_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_target_dir_change_stop_launcher(fncli):
    fncli.call(stop_sensor_command, sensor="launcher")


def test_target_dir_change_create_branch(fncli, flow):
    create_branch(fncli, flow, "target_dir_change")


def test_target_dir_change_commit_file(fncli, flow):
    commit_file(fncli, flow, "target_dir_change", "watched")


def test_target_dir_change_create_pr(fncli, flow):
    create_pr(fncli, flow, "target_dir_change", "watched")


def test_target_dir_change_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "target_dir_change")


def test_target_dir_change_task_is_created_and_waits_unlaunched(fncli, flow):
    flow["target_dir_task"] = fncli.wait_for_state("task from target_dir change test", STEP_TIMEOUT, yielded_with_task(flow, "target_dir_change"))["task_id"]
    fncli.wait_for_state(
        "target_dir change test task PENDING",
        STEP_TIMEOUT,
        lambda s: any(t["id"] == flow["target_dir_task"] and t["status"] == "PENDING" for t in s["tasks"]),
    )


def test_target_dir_change_change_the_target_dir(fncli, flow):
    flow["target_dir_original"] = fncli.snapshot()["results_links"][0]["target_dir"]
    fncli.call(link_set_command, kind="results", target_dir="changed-by-s17/", expect=200)


def test_target_dir_change_start_launcher(fncli):
    fncli.call(start_sensor_command, sensor="launcher")


def test_target_dir_change_task_fails_naming_the_change(fncli, flow):
    task = fncli.wait_for_state(
        "target_dir change test task FAILED",
        TASK_TIMEOUT,
        lambda s: next((t for t in s["tasks"] if t["id"] == flow["target_dir_task"] and t["status"] == "FAILED"), None),
    )
    cause = task.get("state_cause") or ""
    assert "configuration changed" in cause and "target_dir" in cause, f"unexpected cause: {cause!r}"
    assert not [r for r in fncli.snapshot()["results"] if r["task_id"] == flow["target_dir_task"]], "a stale task has a result"


def test_target_dir_change_restore_the_target_dir(fncli, flow):
    fncli.call(link_set_command, kind="results", target_dir=flow["target_dir_original"], expect=200)


# --- sensors stopped, a PR merged, sensors started again -----------------------------------


def test_sensors_restarted_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, tasks_finished)


def test_sensors_restarted_record_counts(fncli, flow):
    record_counts(fncli, flow, "sensors_restarted_before")


def test_sensors_restarted_stop_all_sensors(fncli):
    fncli.call(stop_sensor_command, sensor="all")


def test_sensors_restarted_create_branch(fncli, flow):
    create_branch(fncli, flow, "sensors_restarted")


def test_sensors_restarted_commit_file(fncli, flow):
    commit_file(fncli, flow, "sensors_restarted", "watched")


def test_sensors_restarted_create_pr(fncli, flow):
    create_pr(fncli, flow, "sensors_restarted", "watched")


def test_sensors_restarted_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "sensors_restarted")


def test_sensors_restarted_nothing_happens_while_stopped(fncli, flow):
    time.sleep(max(10, QUIET_TICKS * tick_seconds()))  # no ticks to count: the sensors are off
    fncli.assert_counts(flow["sensors_restarted_before"], "all sensors stopped")


@pytest.mark.parametrize("sensor", ALL_SENSORS)  # in start order: the run-status sensors before the launcher
def test_sensors_restarted_start_sensor(sensor):
    start_sensor(sensor)


def test_sensors_restarted_pr_processed_and_no_task_left_pending(fncli, flow):
    fncli.wait_for_state(
        "the PR with a task (+1 each), and no task PENDING",
        TASK_TIMEOUT,
        lambda s: grew_by_one(flow, "sensors_restarted_before")(s) and all(t["status"] != "PENDING" for t in s["tasks"]),
    )


# --- Teardown ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, final=True)
