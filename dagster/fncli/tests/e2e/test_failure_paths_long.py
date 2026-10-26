"""
The long-running failure paths of the GlobalResource flow: the groups where a task runs to the end or a result is delivered.
Same style as the happy path: one test per fncli command or expected state, in order, on one project, stopping at the first
failure with the last snapshot. Each group of tests leaves the project as the next expects it: resources active, tokens restored,
everything switched back on. The quick groups, which never wait for a task to run, are in test_failure_paths.py (run with
`--e2e failure`), and its docstring lists what no e2e suite covers for now.

It starts with a second project on the same repository, a lost token and its recovery, and a failing task. Then a project that
is disabled while a pull request is merged gets that pull request's task when it is enabled with backfill. The last group is
work in flight: a results resource switched off before delivery (the result is held FAILED and the delivery retry sensor delivers
it once the resource is on). The rules are in ../../../../docs/architecture/revoke-and-enabled.md.

It clears and sets up the project itself, so it runs on its own on a fresh project.

The "nothing happens" checks wait a few sensor ticks (5 ticks of the cluster's sensor interval; E2E_FAST_SENSORS=1 sets it to 1 s for the run). The project is cleared at the start of the run, and kept
afterwards unless E2E_TEARDOWN=1.

All sensors must already be running before the run (`fncli start-sensor --sensor all`); the run does not start them.
"""

import json

import pytest

from fncli.cmds.actions import SETUP_STEPS, TEARDOWN_STEPS
from fncli.cmds.common import DagsterConfig, build_admin_backend_api
from fncli.cmds.project import project_healthcheck_command
from fncli.cmds.secret import (
    delete_gitea_token_command,
    init_git_secret_command,
    verify_git_secret_command,
)
from fncli.cmds.sensor import DELIVERY_RETRY_SENSOR, sensor_status_command
from fncli.cmds.state import (
    resource_set_command,
    project_set_command,
    second_project_setup_command,
    second_project_teardown_command,
)
from fncli.sensors import DagsterAPI
from fncli.tests.e2e.conftest import (
    DELIVERED_STEPS,
    QUIET_SENSORS,
    QUIET_TICKS,
    SECOND_PROJECT,
    SETUP_IDS,
    STEP_TIMEOUT,
    TASK_TIMEOUT,
    TEARDOWN_IDS,
    commit_file,
    counts,
    create_branch,
    create_pr,
    drained,
    grew_by_one,
    logger,
    merge_pr,
    merge_pr_with_task,
    merge_watched_pr,
    pr_of,
    quiet_wait,
    record_counts,
    record_stored,
    result_with,
    results_of,
    stored_without_a_trigger,
    summary,
    task_has_status,
    tasks_finished,
    teardown_step,
    trigger_resource,
    yielded_with_task,
)

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_failure_long]


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


def test_second_project_both_projects_get_a_task(fncli, flow):
    flow["second_project_task_one"] = fncli.wait_for_state("the test project's task", STEP_TIMEOUT, yielded_with_task(flow, "second_project"))["task_id"]
    flow["second_project_task_two"] = fncli.wait_for_state(
        f"{SECOND_PROJECT}'s task", STEP_TIMEOUT, yielded_with_task(flow, "second_project"), project=SECOND_PROJECT
    )["task_id"]
    assert flow["second_project_task_one"] != flow["second_project_task_two"], "both projects share one task for the same PR"


def test_second_project_revoke_second_projects_resource(fncli):
    fncli.call(resource_set_command, kind="trigger", revoked="true", project=SECOND_PROJECT, expect=200)


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
    assert two == flow["second_project_variant_two_before"], f"{SECOND_PROJECT} got something through its revoked resource: {two}"


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


# --- a PR merged while the project is disabled gets a task when it is enabled with backfill ----


def test_backfill_wait_for_tasks_to_finish(fncli):
    # The group counts tasks: the tasks and results of the earlier groups must be done, or they would show up as new
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, drained)


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


# --- work in flight: a results resource switched off before delivery is held FAILED, delivered once the resource is on ----------------


def test_switched_off_results_resource_wait_for_tasks_to_finish(fncli):
    fncli.wait_for_state("no task in flight and every result settled", TASK_TIMEOUT, drained)


def test_switched_off_results_resource_switch_off_resource(fncli):
    fncli.call(resource_set_command, kind="results", enabled="false", expect=200)


def test_switched_off_results_resource_inactive(fncli):
    fncli.wait_for_state("the results resource inactive", STEP_TIMEOUT, lambda s: s["results_resources"][0]["active"] is False)


def test_switched_off_results_resource_merge_pr(fncli, flow):
    """A switched off results resource does not stop the task: it launches and runs."""
    merge_pr_with_task(fncli, flow, "switched_off_results_resource")


def test_switched_off_results_resource_task_succeeds(fncli, flow):
    fncli.wait_for_state("the task SUCCESS", TASK_TIMEOUT, task_has_status(flow, "switched_off_results_resource_task", "SUCCESS"))


def test_switched_off_results_resource_result_is_held_failed(fncli, flow):
    """Recorded by the backend at step UNKNOWN, state FAILED ("results resource switched off"): not final, nothing pushed."""
    fncli.wait_for_state("the result FAILED, held", TASK_TIMEOUT, result_with(flow, "switched_off_results_resource_task", "UNKNOWN", "FAILED"))


def test_switched_off_results_resource_not_delivered_while_off(fncli, flow):
    """The retry sensor lists only the results whose resource is active, so the result stays held."""
    quiet_wait(QUIET_TICKS, [*QUIET_SENSORS, DELIVERY_RETRY_SENSOR])
    snapshot = fncli.snapshot()
    results = results_of(snapshot, flow["switched_off_results_resource_task"])
    assert [(r["step"], r["state"]) for r in results] == [("UNKNOWN", "FAILED")], f"unexpected results\n{json.dumps(summary(snapshot), indent=2)}"


def test_switched_off_results_resource_switch_on_resource(fncli):
    fncli.call(resource_set_command, kind="results", enabled="true", expect=200)


def test_switched_off_results_resource_retry_sensor_delivers(fncli, flow):
    def delivered(snapshot):
        return next(
            (r for r in results_of(snapshot, flow["switched_off_results_resource_task"]) if r["state"] == "DELIVERED" and r["step"] in DELIVERED_STEPS), None
        )

    result = fncli.wait_for_state("the held result DELIVERED by the retry sensor", TASK_TIMEOUT, delivered)
    assert result["number"] and result["url"], f"delivered without a results PR: {result}"


# --- Teardown ---------------------------------------------------------------------------------


@pytest.mark.parametrize("command, options", TEARDOWN_STEPS, ids=TEARDOWN_IDS)
def test_teardown_final(fncli, command, options):
    teardown_step(fncli, command, options, final=True)
