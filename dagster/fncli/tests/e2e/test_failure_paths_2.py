"""
The failure paths of the GlobalResource flow that switch something off or withdraw it: a revoked project, a trigger link
switched off, a GlobalResource (the trigger repository) switched off or revoked, a Secret switched off, and enabling a
project with backfill. Same style as test_failure_paths.py, and run on its own with `--e2e failure2` (or after it with `--e2e`): one test per fncli command or expected state,
in order, on one fresh project, stopping at the first failure with the last snapshot. Each group of tests puts everything
back on before the next.

In every group a pull request is merged while something is off, and none of them may get a task: the rules are in
../../../../docs/architecture/revoke-and-enabled.md. Switching it back on skips the gap, so the pull request still gets no
task, unless the project is enabled with backfill.

Not covered here, only by the webserver and Dagster unit tests: revoking a result that is already held, and a revoked results
link. The project is cleared at the start of the run, and kept afterwards unless E2E_TEARDOWN=1.
"""

import json

import pytest

from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.sensor import ALL_SENSORS
from fncli.cmds.state import global_set_command, link_set_command, project_set_command, secret_set_command
from fncli.tests.e2e import test_failure_paths as base
from fncli.tests.e2e.conftest import (
    SETUP_IDS,
    TEARDOWN_IDS,
    counts,
    quiet_wait,
    start_sensor,
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


def stored_without_a_trigger(flow, key):
    """The pull request is stored (+1) and has no task."""
    prs, tasks = flow[key]
    return lambda snapshot: counts(snapshot) == (prs + 1, tasks)


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
    base.record_counts(fncli, flow, "revoked_project_before")


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
    base.record_counts(fncli, flow, "backfill_before")


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


# --- Teardown ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, final=True)
