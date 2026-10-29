"""
The quick failure paths of the GlobalResource flow. Same style as the happy path: one test per fncli command or expected state,
in order, on one project, stopping at the first failure with the last snapshot. Each group of tests leaves the project as
the next expects it: resources active, tokens restored, everything switched back on.

None of the groups waits for a task to run: they are commands, states and "nothing happens" checks. It starts with an invalid
spec, a pull request outside the watched directory and a revoked trigger resource. Then come the groups that switch something off
or withdraw it: a revoked project, a trigger resource switched off, a GlobalResource (the trigger repository) switched off or
revoked, and a Secret switched off. In each of them a pull request is merged while something is off, and none of them may get
a task. Switching it back on skips the gap, so the pull request still gets no task. The rules are in
../../../../docs/architecture/revoke-and-enabled.md.

The groups where a task runs to the end or a result is delivered (a second project, a lost token and its recovery, a failing
task, enabling a project with backfill, a results resource switched off before delivery) are in test_failure_paths_long.py, run
with `--e2e failure_long`.

Not covered by any e2e suite for now: the scenarios that stop and start sensors were removed, and the reconcile sensor is
expected to make up for sensors being down. Only the nexus-api and Dagster unit tests cover revoking a result that is already
held, and retrying tasks is not covered (on hold until after beta). These behaviours are therefore not checked end to end (the
rules are in revoke-and-enabled.md, "May a waiting task launch?" and "May a finished task's result be delivered?"):
- restarting the ingest sensor does not duplicate pull requests or tasks, also after a trigger resource was revoked and un-revoked;
- a task whose results resource's target_dir changes before it launches fails, and its cause names the change
  (the pinned configuration changed);
- sensors that were all stopped while a pull request was merged catch up when started: the pull request gets one trigger
  and one task, and no task stays PENDING;
- a results resource revoked after the task succeeded and before its delivery: the result is REVOKED and FAILED, never
  delivered, and un-revoking the resource delivers nothing;
- a results resource's target_dir changed after the task succeeded and before its delivery: the result is STALE and FAILED, never
  delivered, and restoring the target_dir delivers nothing;
- a dataset resource revoked while the task is PENDING: the task fails at launch with a cause that starts "revoked: " and names
  the dataset, and has no result;
- a global dataset switched off while the task is PENDING: the task fails at launch with a cause saying the dataset is not
  active and naming it, and has no result.

The "nothing happens" checks wait a few sensor ticks (5 ticks of the cluster's sensor interval; E2E_FAST_SENSORS=1 sets it to 1 s for the run). The project is cleared at the start of the run, and kept
afterwards unless E2E_TEARDOWN=1.

All sensors must already be running before the run (`fncli start-sensor --group all`); the run does not start them.
"""

import pytest

from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.common import build_admin_backend_api
from fncli.cmds.state import (
    global_set_command,
    resource_set_command,
    project_set_command,
    second_project_teardown_command,
    secret_set_command,
)
from fncli.tests.e2e.conftest import (
    QUIET_TICKS,
    SECOND_PROJECT,
    SETUP_IDS,
    STEP_TIMEOUT,
    TEARDOWN_IDS,
    assert_no_new_task,
    commit_file,
    counts,
    create_branch,
    create_pr,
    merge_pr,
    merge_watched_pr,
    pr_of,
    pull_requests,
    quiet_wait,
    record_counts,
    record_stored,
    stored_without_a_trigger,
    summary,
    teardown_step,
    trigger_resource,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_failure]


@pytest.fixture(scope="module")
def flow():
    """What the steps hand on to each other: PR numbers and branches by scenario, counts taken before a change."""
    return {}


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
    assert trigger_resource(snapshot)["active"] is True


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


# --- a PR merged while the resource is revoked never gets a trigger -------------------------------


def test_revoked_resource_record_counts(fncli, flow):
    record_counts(fncli, flow, "revoked_resource_before")


def test_revoked_resource_revoke_resource(fncli):
    fncli.call(resource_set_command, kind="trigger", revoked="true", expect=200)


def test_revoked_resource_inactive(fncli):
    fncli.wait_for_state("the trigger resource inactive", STEP_TIMEOUT, lambda s: trigger_resource(s)["active"] is False)

def test_revoked_resource_create_branch(fncli, flow):
    create_branch(fncli, flow, "revoked_resource")


def test_revoked_resource_commit_file(fncli, flow):
    commit_file(fncli, flow, "revoked_resource", "watched")


def test_revoked_resource_create_pr(fncli, flow):
    create_pr(fncli, flow, "revoked_resource", "watched")


def test_revoked_resource_merge_pr(fncli, flow):
    merge_pr(fncli, flow, "revoked_resource")


def test_revoked_resource_nothing_ingested_while_revoked(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["revoked_resource_before"], "revoked resource")


def test_revoked_resource_unrevoke_resource(fncli):
    fncli.call(resource_set_command, kind="trigger", revoked="false", expect=200)


def test_revoked_resource_missed_pr_not_replayed(fncli, flow):
    """Un-revoking moves the resource's cursor to now: the PR merged while revoked is stored but gets no trigger."""
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["revoked_resource_before"], "PR merged while the resource was revoked, after un-revoking")


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


# --- a PR merged while the trigger resource is switched off gets no task ----------------------------


def test_disabled_resource_record_counts(fncli, flow):
    record_counts(fncli, flow, "disabled_resource_before")


def test_disabled_resource_switch_off_resource(fncli):
    fncli.call(resource_set_command, kind="trigger", enabled="false", expect=200)


def test_disabled_resource_inactive(fncli):
    fncli.wait_for_state("the trigger resource inactive", STEP_TIMEOUT, lambda s: trigger_resource(s)["active"] is False)


def test_disabled_resource_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "disabled_resource")


def test_disabled_resource_nothing_ingested_while_off(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["disabled_resource_before"], "trigger resource switched off")


def test_disabled_resource_switch_on_resource(fncli):
    fncli.call(resource_set_command, kind="trigger", enabled="true", expect=200)


def test_disabled_resource_missed_pr_not_replayed(fncli, flow):
    assert_no_new_task(fncli, flow, "disabled_resource_before", "PR merged while the trigger resource was off, after switching it on")


# --- a PR merged while the GlobalResource is switched off gets no task ------------------------


def test_disabled_global_record_counts(fncli, flow):
    record_counts(fncli, flow, "disabled_global_before")


def test_disabled_global_switch_off_global(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="false", expect=200)


def test_disabled_global_resource_inactive(fncli):
    fncli.wait_for_state("the trigger resource inactive", STEP_TIMEOUT, lambda s: trigger_resource(s)["active"] is False)


def test_disabled_global_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "disabled_global")


def test_disabled_global_nothing_ingested_while_off(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["disabled_global_before"], "GlobalResource switched off")


def test_disabled_global_switch_on_global(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="true", expect=200)


def test_disabled_global_resource_active_again(fncli):
    fncli.wait_for_state("the trigger resource active", STEP_TIMEOUT, lambda s: trigger_resource(s)["active"] is True)


def test_disabled_global_missed_pr_not_replayed(fncli, flow):
    """Catching up stores the PR merged while the GlobalResource was off, and it gets no task."""
    assert_no_new_task(fncli, flow, "disabled_global_before", "PR merged while the GlobalResource was off, after switching it on")


# --- a PR merged while the GlobalResource is revoked gets no task -----------------------------


def test_revoked_global_record_counts(fncli, flow):
    record_counts(fncli, flow, "revoked_global_before")


def test_revoked_global_revoke_global(fncli):
    fncli.call(global_set_command, kind="trigger", revoked="true", expect=200)


def test_revoked_global_resource_inactive(fncli):
    fncli.wait_for_state("the trigger resource inactive", STEP_TIMEOUT, lambda s: trigger_resource(s)["active"] is False)


def test_revoked_global_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "revoked_global")


def test_revoked_global_nothing_ingested_while_revoked(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["revoked_global_before"], "GlobalResource revoked")


def test_revoked_global_restore_global(fncli):
    fncli.call(global_set_command, kind="trigger", revoked="false", expect=200)


def test_revoked_global_resource_active_again(fncli):
    fncli.wait_for_state("the trigger resource active", STEP_TIMEOUT, lambda s: trigger_resource(s)["active"] is True)


def test_revoked_global_missed_pr_not_replayed(fncli, flow):
    assert_no_new_task(fncli, flow, "revoked_global_before", "PR merged while the GlobalResource was revoked, after restoring it")


# --- a PR merged while the trigger repository's Secret is switched off gets no task -----------


def test_disabled_secret_record_counts(fncli, flow):
    record_counts(fncli, flow, "disabled_secret_before")


def test_disabled_secret_switch_off_secret(fncli):
    fncli.call(secret_set_command, entity="trigger", enabled="false", expect=200)


def test_disabled_secret_switches_off_the_repository(fncli):
    """Switching a Secret off switches off every repository that uses it."""
    fncli.wait_for_state("the trigger resource inactive", STEP_TIMEOUT, lambda s: trigger_resource(s)["active"] is False)


def test_disabled_secret_merge_pr(fncli, flow):
    merge_watched_pr(fncli, flow, "disabled_secret")


def test_disabled_secret_nothing_ingested_while_off(fncli, flow):
    quiet_wait(QUIET_TICKS)
    fncli.assert_counts(flow["disabled_secret_before"], "Secret switched off")


def test_disabled_secret_switch_on_secret(fncli):
    fncli.call(secret_set_command, entity="trigger", enabled="true", expect=200)


def test_disabled_secret_repository_stays_off(fncli):
    """Switching the Secret on changes only the Secret: the repository stays off until it is switched on itself."""
    assert trigger_resource(fncli.snapshot())["active"] is False


def test_disabled_secret_switch_on_repository(fncli):
    fncli.call(global_set_command, kind="trigger", enabled="true", expect=200)


def test_disabled_secret_resource_active_again(fncli):
    fncli.wait_for_state("the trigger resource active", STEP_TIMEOUT, lambda s: trigger_resource(s)["active"] is True)


def test_disabled_secret_missed_pr_not_replayed(fncli, flow):
    assert_no_new_task(fncli, flow, "disabled_secret_before", "PR merged while the Secret was off, after switching it back on")


# --- Teardown ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, final=True)
