"""
The failure paths of the GlobalResource flow that switch something off or withdraw it: a revoked project, a trigger link
switched off, a GlobalResource (the trigger repository) switched off or revoked, a Secret switched off, and enabling a
project with backfill. Same style as test_failure_paths.py, and run on its own with `--e2e failure2` (or after it with `--e2e`): one test per fncli command or expected state,
in order, on one fresh project, stopping at the first failure with the last snapshot. Each group of tests puts everything
back on before the next.

In every group a pull request is merged while something is off, and none of them may get a task: the rules are in
../../../../docs/architecture/revoke-and-enabled.md. Switching it back on skips the gap, so the pull request still gets no
task, unless the project is enabled with backfill.

Then the work in flight: a results link revoked, or its target_dir changed, after the task launched and before its delivery (the
result is final REVOKED or STALE and un-doing the change delivers nothing); a results link switched off before delivery (the
result is held FAILED and the delivery retry sensor delivers it once the link is on); and a dataset revoked, or switched off
globally, while a task is PENDING (the task fails at launch naming the dataset).

Not covered here, only by the webserver and Dagster unit tests: revoking a result that is already held. Retrying tasks is
not covered (on hold until after beta). The project is cleared at the start of the run, and kept afterwards unless E2E_TEARDOWN=1.
"""

import json

import pytest

from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.sensor import ALL_SENSORS, DELIVERY_RETRY_SENSOR, start_sensor_command, stop_sensor_command
from fncli.cmds.state import global_set_command, link_set_command, project_set_command, secret_set_command
from fncli.tests.e2e import test_failure_paths as base
from fncli.tests.e2e.conftest import (
    QUIET_SENSORS,
    SETUP_IDS,
    TEARDOWN_IDS,
    counts,
    quiet_wait,
    start_sensor,
    stored_count,
    summary,
    teardown_step,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_failure2]

QUIET_TICKS = base.QUIET_TICKS
STEP_TIMEOUT = base.STEP_TIMEOUT
TASK_TIMEOUT = base.TASK_TIMEOUT


@pytest.fixture(scope="module")
def flow():
    """What the steps hand on to each other: PR numbers and branches by group, counts taken before a change."""
    return {}


def merge_watched_pr(fncli, flow, key):
    base.create_branch(fncli, flow, key)
    base.commit_file(fncli, flow, key, "watched")
    base.create_pr(fncli, flow, key, "watched")
    base.merge_pr(fncli, flow, key)


def assert_no_new_task(fncli, flow, key, what):
    """After a few sensor ticks the project still has the tasks it had when the counts were taken."""
    quiet_wait(QUIET_TICKS)
    snapshot = fncli.snapshot()
    assert len(snapshot["tasks"]) == flow[key][1], f"{what}: a task was created\n{json.dumps(summary(snapshot), indent=2)}"


def record_stored(fncli, flow, key):
    """Records the counts and, for the link that gets no trigger, how many pull requests the repository has stored."""
    base.record_counts(fncli, flow, key)
    flow[f"{key}_stored"] = stored_count(fncli.snapshot())


def stored_without_a_trigger(flow, key):
    """The pull request is stored (+1, read from the repository: the link gets no trigger for it) and has no task."""
    return lambda snapshot: stored_count(snapshot) == flow[f"{key}_stored"] + 1 and counts(snapshot) == flow[key]


# --- Preflight: the admin login the revoke tests need -----------------------------------------


def test_admin_login(fncli):
    base.test_admin_login(fncli)


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
    assert base.trigger_link(snapshot)["active"] is True


# --- a PR merged while the project is revoked is stored and gets no task --------------------


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
    base.record_counts(fncli, flow, "disabled_link_before")


def test_disabled_link_switch_off_link(fncli):
    fncli.call(link_set_command, kind="trigger", enabled="false", expect=200)


def test_disabled_link_link_inactive(fncli):
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: base.trigger_link(s)["active"] is False)


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
    base.record_counts(fncli, flow, "disabled_global_before")


def test_disabled_global_switch_off_global(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="false", expect=200)


def test_disabled_global_link_inactive(fncli):
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: base.trigger_link(s)["active"] is False)


def test_disabled_global_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "disabled_global")


def test_disabled_global_nothing_ingested_while_off(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["disabled_global_before"], "GlobalResource switched off")


def test_disabled_global_switch_on_global(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="true", expect=200)


def test_disabled_global_link_active_again(fncli):
    fncli.wait_for_state("the trigger link active", STEP_TIMEOUT, lambda s: base.trigger_link(s)["active"] is True)


def test_disabled_global_missed_pr_not_replayed(fncli, flow):
    """Catching up stores the PR merged while the GlobalResource was off, and it gets no task."""
    assert_no_new_task(fncli, flow, "disabled_global_before", "PR merged while the GlobalResource was off, after switching it on")


# --- a PR merged while the GlobalResource is revoked gets no task -----------------------------


def test_revoked_global_record_counts(fncli, flow):
    base.record_counts(fncli, flow, "revoked_global_before")


def test_revoked_global_revoke_global(fncli):
    fncli.call(global_set_command, kind="trigger", revoked="true", expect=200)


def test_revoked_global_link_inactive(fncli):
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: base.trigger_link(s)["active"] is False)


def test_revoked_global_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "revoked_global")


def test_revoked_global_nothing_ingested_while_revoked(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["revoked_global_before"], "GlobalResource revoked")


def test_revoked_global_restore_global(fncli):
    fncli.call(global_set_command, kind="trigger", revoked="false", expect=200)


def test_revoked_global_link_active_again(fncli):
    fncli.wait_for_state("the trigger link active", STEP_TIMEOUT, lambda s: base.trigger_link(s)["active"] is True)


def test_revoked_global_missed_pr_not_replayed(fncli, flow):
    assert_no_new_task(fncli, flow, "revoked_global_before", "PR merged while the GlobalResource was revoked, after restoring it")


# --- a PR merged while the trigger repository's Secret is switched off gets no task -----------


def test_disabled_secret_record_counts(fncli, flow):
    base.record_counts(fncli, flow, "disabled_secret_before")


def test_disabled_secret_switch_off_secret(fncli):
    fncli.call(secret_set_command, entity="trigger", enabled="false", expect=200)


def test_disabled_secret_switches_off_the_repository(fncli):
    """Switching a Secret off switches off every repository that uses it."""
    fncli.wait_for_state("the trigger link inactive", STEP_TIMEOUT, lambda s: base.trigger_link(s)["active"] is False)


def test_disabled_secret_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "disabled_secret")


def test_disabled_secret_nothing_ingested_while_off(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["disabled_secret_before"], "Secret switched off")


def test_disabled_secret_switch_on_secret(fncli):
    fncli.call(secret_set_command, entity="trigger", enabled="true", expect=200)


def test_disabled_secret_repository_stays_off(fncli):
    """Switching the Secret on changes only the Secret: the repository stays off until it is switched on itself."""
    assert base.trigger_link(fncli.snapshot())["active"] is False


def test_disabled_secret_switch_on_repository(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="true", expect=200)


def test_disabled_secret_link_active_again(fncli):
    fncli.wait_for_state("the trigger link active", STEP_TIMEOUT, lambda s: base.trigger_link(s)["active"] is True)


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
    fncli.wait_for_state("no task in flight", TASK_TIMEOUT, base.tasks_finished)


# --- Work in flight: the task is past (or before) its launch when a setting changes ---------------------------------------------

DELIVERED_STEPS = ["OPENED", "MERGED"]


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
    pr = fncli.wait_for_state(f"PR #{flow[f'{key}_pr']} YIELDED with a task_id", STEP_TIMEOUT, base.yielded_with_task(flow, key))
    flow[f"{key}_task"] = pr["task_id"]


def assert_never_delivered(fncli, flow, key, step):
    """After a few ticks, the sensors included that retry a delivery, the task's one result is still at the final step, with no results PR."""
    quiet_wait(QUIET_TICKS, [*QUIET_SENSORS, DELIVERY_RETRY_SENSOR])
    snapshot = fncli.snapshot()
    results = results_of(snapshot, flow[f"{key}_task"])
    assert [r["step"] for r in results] == [step], f"expected one result at {step}\n{json.dumps(summary(snapshot), indent=2)}"
    assert results[0]["state"] == "FAILED" and not results[0]["number"] and not results[0]["url"], f"the result was delivered: {results[0]}"


# --- a results link revoked after the task launched: the result is REVOKED, never delivered -----------------------------------


def test_revoked_results_link_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, base.drained)


def test_revoked_results_link_hold_delivery(fncli):
    """Delivery is held so the link is revoked after the task succeeded and before its results are delivered."""
    fncli.call(stop_sensor_command, sensor="delivery")


def test_revoked_results_link_merge_pr(fncli, flow):
    merge_pr_with_task(fncli, flow, "revoked_results_link")


def test_revoked_results_link_task_succeeds(fncli, flow):
    fncli.wait_for_state("the task SUCCESS", TASK_TIMEOUT, task_has_status(flow, "revoked_results_link_task", "SUCCESS"))


def test_revoked_results_link_revoke_link(fncli):
    fncli.call(link_set_command, kind="results", revoked="true", expect=200)


def test_revoked_results_link_is_revoked(fncli):
    fncli.wait_for_state("the results link revoked", STEP_TIMEOUT, lambda s: s["results_links"][0]["revoked"] is True)


def test_revoked_results_link_release_delivery(fncli):
    fncli.call(start_sensor_command, sensor="delivery")


def test_revoked_results_link_result_is_revoked(fncli, flow):
    fncli.wait_for_state("the result REVOKED", TASK_TIMEOUT, result_with(flow, "revoked_results_link_task", "REVOKED", "FAILED"))


def test_revoked_results_link_unrevoke_link(fncli):
    fncli.call(link_set_command, kind="results", revoked="false", expect=200)


def test_revoked_results_link_unrevoking_delivers_nothing(fncli, flow):
    """REVOKED is final: the retry sensor does not pick it up once the link is active again."""
    fncli.wait_for_state("the results link active", STEP_TIMEOUT, lambda s: s["results_links"][0]["active"] is True)
    assert_never_delivered(fncli, flow, "revoked_results_link", "REVOKED")


# --- a results link's target_dir changed after the task launched: the result is STALE, never delivered ------------------------


def test_stale_result_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, base.drained)


def test_stale_result_hold_delivery(fncli):
    fncli.call(stop_sensor_command, sensor="delivery")


def test_stale_result_merge_pr(fncli, flow):
    merge_pr_with_task(fncli, flow, "stale_result")


def test_stale_result_task_succeeds(fncli, flow):
    fncli.wait_for_state("the task SUCCESS", TASK_TIMEOUT, task_has_status(flow, "stale_result_task", "SUCCESS"))


def test_stale_result_change_the_target_dir(fncli, flow):
    flow["stale_result_target_dir"] = fncli.snapshot()["results_links"][0]["target_dir"]
    fncli.call(link_set_command, kind="results", target_dir="changed-after-run/", expect=200)


def test_stale_result_release_delivery(fncli):
    fncli.call(start_sensor_command, sensor="delivery")


def test_stale_result_result_is_stale(fncli, flow):
    fncli.wait_for_state("the result STALE", TASK_TIMEOUT, result_with(flow, "stale_result_task", "STALE", "FAILED"))


def test_stale_result_restore_the_target_dir(fncli, flow):
    fncli.call(link_set_command, kind="results", target_dir=flow["stale_result_target_dir"], expect=200)


def test_stale_result_restoring_delivers_nothing(fncli, flow):
    """STALE is final: restoring the target_dir does not deliver it."""
    assert_never_delivered(fncli, flow, "stale_result", "STALE")


# --- a results link switched off before delivery: the result is held FAILED, delivered once the link is on ----------------------


def test_switched_off_results_link_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, base.drained)


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


# --- a dataset revoked while the task is PENDING: it fails at launch naming the dataset ----------------------------------------


def hold_launcher_with_pending_task(fncli, flow, key):
    """The launcher stopped, a watched PR merged, and its task waiting PENDING."""
    merge_pr_with_task(fncli, flow, key)
    fncli.wait_for_state(f"task {flow[f'{key}_task']} PENDING", STEP_TIMEOUT, task_has_status(flow, f"{key}_task", "PENDING"))
    flow[f"{key}_dataset"] = fncli.snapshot()["dataset_links"][0]["dataset"]


def failed_at_launch(fncli, flow, key):
    task = fncli.wait_for_state(f"task {flow[f'{key}_task']} FAILED", TASK_TIMEOUT, task_has_status(flow, f"{key}_task", "FAILED"))
    assert not results_of(fncli.snapshot(), flow[f"{key}_task"]), "a task that failed at launch has a result"
    return task.get("state_cause") or ""


def test_revoked_dataset_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, base.drained)


def test_revoked_dataset_stop_launcher(fncli):
    fncli.call(stop_sensor_command, sensor="launcher")


def test_revoked_dataset_task_waits_unlaunched(fncli, flow):
    hold_launcher_with_pending_task(fncli, flow, "revoked_dataset")


def test_revoked_dataset_revoke_dataset_link(fncli):
    fncli.call(link_set_command, kind="dataset", revoked="true", expect=200)


def test_revoked_dataset_link_revoked(fncli):
    fncli.wait_for_state("the dataset link revoked", STEP_TIMEOUT, lambda s: s["dataset_links"][0]["revoked"] is True)


def test_revoked_dataset_start_launcher(fncli):
    fncli.call(start_sensor_command, sensor="launcher")


def test_revoked_dataset_task_fails_naming_the_dataset(fncli, flow):
    cause = failed_at_launch(fncli, flow, "revoked_dataset")
    assert cause.startswith("revoked: ") and flow["revoked_dataset_dataset"].lower() in cause.lower(), f"unexpected cause: {cause!r}"


def test_revoked_dataset_unrevoke_dataset_link(fncli):
    fncli.call(link_set_command, kind="dataset", revoked="false", expect=200)


def test_revoked_dataset_link_active_again(fncli):
    fncli.wait_for_state("the dataset link active", STEP_TIMEOUT, lambda s: s["dataset_links"][0]["active"] is True)


# --- the global dataset switched off while the task is PENDING: it fails at launch naming the dataset -------------------------


def test_disabled_dataset_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, base.drained)


def test_disabled_dataset_stop_launcher(fncli):
    fncli.call(stop_sensor_command, sensor="launcher")


def test_disabled_dataset_task_waits_unlaunched(fncli, flow):
    hold_launcher_with_pending_task(fncli, flow, "disabled_dataset")


def test_disabled_dataset_switch_off_global_dataset(fncli):
    fncli.call(global_set_command, kind="dataset", enabled="false", expect=200)


def test_disabled_dataset_link_inactive(fncli):
    fncli.wait_for_state("the dataset link inactive", STEP_TIMEOUT, lambda s: s["dataset_links"][0]["active"] is False)


def test_disabled_dataset_start_launcher(fncli):
    fncli.call(start_sensor_command, sensor="launcher")


def test_disabled_dataset_task_fails_naming_the_dataset(fncli, flow):
    """Switched off is not revoked: the cause is "Dataset <name> is not active in project <project>"."""
    cause = failed_at_launch(fncli, flow, "disabled_dataset")
    assert "not active" in cause and flow["disabled_dataset_dataset"].lower() in cause.lower(), f"unexpected cause: {cause!r}"


def test_disabled_dataset_switch_on_global_dataset(fncli):
    fncli.call(global_set_command, kind="dataset", enabled="true", expect=200)


def test_disabled_dataset_link_active_again(fncli):
    fncli.wait_for_state("the dataset link active", STEP_TIMEOUT, lambda s: s["dataset_links"][0]["active"] is True)


# --- Teardown ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, final=True)
