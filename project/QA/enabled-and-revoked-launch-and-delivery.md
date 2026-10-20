# Enabled and revoked rules: waiting tasks, running tasks and results

What switching something off, or revoking it, does to work that already exists: a task waiting to launch, a task running, and a result waiting to be delivered. The same two flags as in [enabled and revoked: pull requests and triggers](enabled-and-revoked-ingest-side.md), at the same levels. The end-to-end suites cover one case here (a results link switched off before delivery). Three of the seven behaviours that were removed from them are here (marked in their titles); the others are in [task pinning](task-pinning.md) and [sensors, restarts and catch-up](sensors-restarts-and-catch-up.md). Apart from the one held-result case, everything here is only unit-tested.

The rules in words ([docs/architecture/revoke-and-enabled.md#may-a-waiting-task-launch] and [docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered]):

- A waiting (`PENDING`) task of an enabled project is checked at launch, in this order: something it uses is revoked or deleted (cause starts "revoked: "); its pinned configuration changed; its dataset link is not active; its dataset's Secret is disabled. The first that applies decides, and the task goes `FAILED` with that cause. A project that is not enabled is not looked at: its waiting tasks wait.
- Switching off does not stop launching, except for the project and the dataset. A running task is never stopped.
- A finished task's result is decided when it is created, in this order: the task is not `SUCCESS` (409); something it uses is revoked or deleted (`REVOKED`, final); the configuration changed (`STALE`, final; see [task pinning](task-pinning.md)); the results link, ResultsRepository or GitProvider is switched off (held: step `UNKNOWN`, state `FAILED`, delivered by the retry sensor once active); otherwise delivered.
- A failed task stays failed until it is retried; nothing re-evaluates it.

Needs: the dev project with all sensors running, an administrator login for `--revoked`, and a task image that runs long enough to change something while it is `RUNNING` (check how long the reference image takes). Use the two recipes in [the index](README.md): "Make a change while a task is still PENDING" and "Make a change while a task is RUNNING or before delivery". Undo each change at the end and wait for every task and result to settle before the next case.

## A disabled project's waiting task waits, and launches when the project is enabled

1. Make the change while the task is `PENDING`: `fncli project-set --enabled false`.
2. Start the launcher and wait five intervals. Then `fncli project-set --enabled true`.

- **Expected:** the task stays `PENDING` (not failed) while the project is off, and launches after step 2 and runs.
- **Rule:** the launcher only looks at enabled projects; waiting costs nothing ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_launcher.py` (`test_only_enabled_projects_are_acted_on`) and `webserver/tests/test_projects_api.py`. No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A revoked project's waiting task fails at launch

1. Make the change while the task is `PENDING`: `fncli project-set --revoked true`.
2. Start the launcher.
3. `fncli project-set --revoked false`, then look at the task again.

- **Expected:** the task goes `FAILED` with a cause that starts "revoked: ". No run, no result. After step 3 it stays `FAILED`.
- **Rule:** a task whose project is revoked fails at launch; a failed task needs a retry ([Responsibility: the webserver owns the record and the rules; Dagster carries out decisions]; [docs/architecture/revoke-and-enabled.md#what-each-state-does]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (the revoked cause; the project is named first), `webserver/tests/test_task_launch.py`. No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A project that is both revoked and disabled keeps its waiting tasks waiting; they fail once it is enabled

1. Task `PENDING`, launcher stopped. `fncli project-set --revoked true`, then `fncli project-set --enabled false`.
2. Start the launcher, wait five intervals.
3. `fncli project-set --enabled true`.

- **Expected:** after step 2 the task is still `PENDING`. After step 3 it goes `FAILED` with a "revoked: " cause. Restore with `fncli project-set --revoked false`.
- **Rule:** the launcher only reads enabled projects, so they fail once it is enabled ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_launcher.py` (`test_a_disabled_project_keeps_its_task_pending_until_it_is_enabled_then_the_backend_fails_it`). It mocks the webserver's answer and misses the live launcher.
- [ ] Pass
- [ ] Fail — notes:

## A dataset link revoked while the task waits fails it at launch (removed from the end-to-end suites)

1. Task `PENDING`, launcher stopped. `fncli link-set dataset --revoked true`.
2. Start the launcher.
3. `fncli link-set dataset --revoked false`.

- **Expected:** the task goes `FAILED` with a cause that starts "revoked: " and names the dataset. No run and no result. It stays `FAILED` after step 3.
- **Rule:** anything the task uses that is revoked fails it at launch ([docs/architecture/revoke-and-enabled.md#may-a-waiting-task-launch]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_a_revoked_resource_fails_with_the_revoked_cause`), `webserver/tests/test_task_launch.py`, `dagster/app/tests/test_task_launcher.py`. Removed from the end-to-end failure suite; never tested with the live launcher.
- [ ] Pass
- [ ] Fail — notes:

## A global dataset switched off while the task waits fails it at launch (removed from the end-to-end suites)

1. Task `PENDING`, launcher stopped. `fncli global-set dataset --enabled false`.
2. Start the launcher.
3. `fncli global-set dataset --enabled true`.

- **Expected:** the task goes `FAILED` with a cause saying the dataset is not active, and naming it. It is not described as revoked. No run, no result.
- **Rule:** a task needs an active dataset link; a switched-off dataset is "not active", not "revoked" ([docs/architecture/revoke-and-enabled.md#may-a-waiting-task-launch]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_a_switched_off_global_dataset_fails_as_not_active_not_revoked`), `webserver/tests/test_task_launch.py`. Removed from the end-to-end failure suite. They miss the live launcher.
- [ ] Pass
- [ ] Fail — notes:

## A dataset link switched off, or a global dataset revoked, fails a waiting task

1. Task `PENDING`, launcher stopped. `fncli link-set dataset --enabled false`. Start the launcher. Note the cause. `fncli link-set dataset --enabled true`.
2. Repeat the setup with a new task. `PATCH /global/datasets/<id>` with `{"revoked": true}` (administrator). Start the launcher. Note the cause. Restore `{"revoked": false}`.

- **Expected:** step 1: `FAILED`, the cause names the dataset and the project and says it is not active. Step 2: `FAILED`, the cause starts "revoked: " and names the dataset.
- **Rule:** the same two causes as in the previous cases, from the other levels ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_a_dataset_link_switched_off_fails_naming_the_dataset_and_project`, `test_a_revoked_global_resource_provider_or_project_is_named_until_it_is_restored`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A revoked trigger link or results link fails a waiting task

1. Task `PENDING`, launcher stopped. `fncli link-set trigger --revoked true`. Start the launcher. Note the cause. Restore.
2. New task, same again with `fncli link-set results --revoked true`, then with `fncli global-set trigger --revoked true`.

- **Expected:** each time the task is `FAILED` with a cause that starts "revoked: " and names what is revoked. If several things are revoked, every one is named, the project first.
- **Rule:** "anything the task uses" covers the project, the trigger, the dataset and the results repository, and their GlobalResources and GitProviders ([docs/architecture/revoke-and-enabled.md#may-a-waiting-task-launch]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_every_revoked_name_is_in_the_cause`, `test_everything_revoked_is_named_once_the_project_first`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A trigger link switched off does not stop a waiting task

1. Task `PENDING`, launcher stopped. `fncli link-set trigger --enabled false`. Start the launcher.
2. `fncli link-set trigger --enabled true`.

- **Expected:** the task launches, runs and finishes; its result is delivered. Switching off stops new work only.
- **Rule:** a switched-off trigger link, repository or GitProvider does not stop a task that is not launched yet ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_nothing_is_revoked_for_a_current_task_or_for_links_only_switched_off`), `webserver/tests/test_results_and_delivery.py`. No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A task failed by a rule stays failed

1. After any case above that failed a task, restore the setting that caused it. Wait ten intervals.
2. Look at the task and the pull request.

- **Expected:** the task stays `FAILED` with its cause. It is not relaunched and the pull request is not re-run. Retrying a task is on hold for the beta ([permissions and out of scope](permissions-and-out-of-scope.md)).
- **Rule:** a task failed by a rule stays failed until it is retried; nothing re-evaluates it ([Responsibility: the webserver owns the record and the rules; Dagster carries out decisions]).
- **Automated by:** Partly automated: `webserver/tests/test_task_launch.py` (a repeat changes nothing; a non-`PENDING` task is 409). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A running task is not stopped when its project is disabled; its result is delivered

1. Merge a watched pull request. While the task is `RUNNING`: `fncli project-set --enabled false`.
2. Wait until the task finishes and the result appears. Then `fncli project-set --enabled true`.

- **Expected:** the task finishes `SUCCESS`; its result is delivered (`OPENED`) although the project is disabled.
- **Rule:** a disabled project's running tasks finish and its finished tasks' results are delivered ([docs/architecture/revoke-and-enabled.md#what-each-state-does]).
- **Automated by:** Partly automated: `webserver/tests/test_projects_api.py` (`test_enable_and_disable_ignore_tasks_in_flight`); the delivery sensors do not look at the project's `enabled`. No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A running task is not stopped when its project is revoked; its result is `REVOKED`

1. Merge a watched pull request. While the task is `RUNNING`: `fncli project-set --revoked true`.
2. Wait until the task finishes. Then `fncli project-set --revoked false`.

- **Expected:** the task finishes `SUCCESS`. Its result is `REVOKED` with state `FAILED`, never delivered; no branch or results pull request. After step 2 the result is still `REVOKED` (final) and nothing is delivered.
- **Rule:** a revoke blocks the work and a result recorded while it holds is never delivered; a running task is not stopped ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py` (the `POST` that creates the result is `REVOKED` when the project is revoked) and `webserver/tests/test_task_config.py`. No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A running task is not stopped when its dataset is switched off or revoked

1. Merge a watched pull request. While the task is `RUNNING`: `fncli global-set dataset --enabled false`. Wait for the result. Restore.
2. New task. While it is `RUNNING`: `fncli link-set dataset --revoked true`. Wait for the result. Restore.

- **Expected:** step 1: the task finishes `SUCCESS` and its result is delivered. Step 2: the task finishes `SUCCESS` and its result is `REVOKED`, never delivered.
- **Rule:** a dataset switched off does not touch finished results; a revoked dataset makes the result `REVOKED` ([docs/architecture/revoke-and-enabled.md#what-each-state-does]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py` (`test_post_result_is_revoked_when_the_dataset_link_is_revoked_or_deleted`, `test_post_result_is_not_revoked_when_the_trigger_and_dataset_links_are_only_switched_off`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A trigger link or trigger repository revoked while the task runs makes the result `REVOKED`

1. Merge a watched pull request. While the task is `RUNNING`: `fncli link-set trigger --revoked true`. Wait for the result. Restore.
2. New task. While it is `RUNNING`: `fncli global-set trigger --revoked true`. Wait for the result. Restore.

- **Expected:** each time the result is `REVOKED` with state `FAILED`, never delivered, and un-revoking later delivers nothing. The pull request was already `YIELDED`.
- **Rule:** the result is decided from what the task uses when it is created ([docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py` (`test_post_result_is_revoked_when_the_trigger_link_is_revoked`, `test_post_result_is_revoked_when_a_global_resource_provider_or_project_is_revoked`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A results link switched off while the task runs holds the result, which is delivered once the link is on

1. Merge a watched pull request. While the task is `RUNNING`: `fncli link-set results --enabled false`.
2. Wait for the task to finish. Look at the result for ten intervals.
3. `fncli link-set results --enabled true`. Watch.

- **Expected:** the task is `SUCCESS`. The result is recorded with step `UNKNOWN`, state `FAILED` and an error saying the results link is switched off; nothing is pushed and it stays that way for as long as the link is off. After step 3 the delivery retry sensor delivers it: step `OPENED`, state `DELIVERED`, with a `number` and `url`.
- **Rule:** a switched-off results link holds the result; the retry sensor delivers it once the link is active ([Enabled, revoked and soft delete]; [Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "work in flight: a results link switched off before delivery is held FAILED, delivered once the link is on" (`dagster/fncli/tests/e2e/test_failure_paths.py`), which switches the link off before the task starts, not while it runs; written, never run on a cluster. `webserver/tests/test_results_and_delivery.py` (`test_post_result_through_a_switched_off_link_is_failed_and_waits`). [TESTING.md](../TESTING.md#checks-that-have-never-run-on-a-cluster) lists its assumptions as unchecked.
- [ ] Pass
- [ ] Fail — notes:

## A results GlobalResource or its GitProvider switched off holds the result

1. Merge a watched pull request. While the task is `RUNNING`: `fncli global-set results --enabled false`. Wait for the result (held).
2. `fncli global-set results --enabled true`. Wait for delivery.
3. New task. Switch the GitProvider off with `PATCH /global/providers/<id>` `{"enabled": false}` while it runs. Wait for the result. Switch it on.

- **Expected:** each time the result is held (step `UNKNOWN`, state `FAILED`), not delivered, and delivered by the retry sensor after the switch-on. (Switching the GitProvider off also stops the trigger repository; the task you already have is unaffected.)
- **Rule:** the results link, the ResultsRepository and the GitProvider are all in the "switched off" test ([docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py` (`test_post_result_through_a_switched_off_global_repository_or_provider_is_failed_and_waits`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A results link revoked after the task succeeded and before delivery leaves the result `REVOKED` (removed from the end-to-end suites)

1. Merge a watched pull request. While the task is `RUNNING` (preferred), or after it is `SUCCESS` with the delivery sensors stopped (see the recipe and its caution in [the index](README.md)): `fncli link-set results --revoked true`.
2. Wait for the result.
3. `fncli link-set results --revoked false`. Wait ten intervals.

- **Expected:** the result is step `REVOKED`, state `FAILED`, never delivered: no branch, no results pull request. Un-revoking the link delivers nothing; the result stays `REVOKED`.
- **Rule:** a revoked ProjectResultsRepository makes the result final and never delivered ([docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py`, `webserver/tests/test_task_config.py`. Removed from the end-to-end failure suite. They miss the live delivery path.
- [ ] Pass
- [ ] Fail — notes:

## A results GlobalResource revoked before delivery leaves the result `REVOKED`

1. Merge a watched pull request. While the task is `RUNNING`: `fncli global-set results --revoked true`.
2. Wait for the result. Then `fncli global-set results --revoked false`.

- **Expected:** the result is `REVOKED`, never delivered, final.
- **Rule:** same as the previous case, from the GlobalResource ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py` (`test_post_result_is_revoked_when_a_global_resource_provider_or_project_is_revoked`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A revoke while a result is held applies on the next attempt, and a results-side revoke pauses the retry

1. Hold a result: merge a watched pull request, `fncli link-set results --enabled false` while it runs, wait for the held result.
2. `fncli project-set --revoked true`. Then `fncli link-set results --enabled true`. Watch the result.
3. Hold another result the same way. `fncli link-set results --revoked true`, then `fncli link-set results --enabled true`. Wait ten intervals. Then `fncli link-set results --revoked false`.

- **Expected:** step 2: the retry sensor's next attempt calls the results route, which sets the held result `REVOKED` (final, never delivered). Restore `fncli project-set --revoked false`. Step 3: while the link is revoked it is not active, so the retry is paused and the result stays held; after un-revoking, it is delivered (check: the sources say the retry resumes on un-revoke; a result recorded before a revoke keeps its step and state until the route is called for it again).
- **Rule:** known limits: a result recorded before a revoke keeps its step until `POST /projects/<pid>/results` is called again; after a revoke on the results side the retry is paused and resumes on un-revoke ([docs/architecture/revoke-and-enabled.md#known-limits]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py` (`test_post_result_revokes_an_existing_held_result_when_something_is_revoked_later`, `test_post_result_revokes_an_existing_result_from_each_non_final_step_and_state`). The failure suite's docstring says only the unit tests cover revoking a result that is already held.
- [ ] Pass
- [ ] Fail — notes:

## Revoked wins over switched off, and changed wins over switched off

1. Merge a watched pull request. While the task is `RUNNING`: `fncli link-set results --enabled false` and `fncli link-set trigger --revoked true`. Wait for the result.
2. Restore. New task. While it runs: `fncli link-set results --enabled false` and `fncli link-set results --target-dir <another directory>`. Wait for the result. Restore.

- **Expected:** step 1: the result is `REVOKED`, not held. Step 2: the result is `STALE`, not held.
- **Rule:** the order is revoked, then changed, then switched off ([docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py` (`test_post_result_revoked_beats_switched_off`, `test_post_result_stale_beats_switched_off_and_is_final`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## Deleting a link, a GlobalResource or a project with work in flight

Use scratch GlobalResources or the second project. Destructive: not on the main test project.

1. Task `RUNNING`; `DELETE` its project's results link (or force-delete the scratch ResultsRepository). Wait for the result.
2. Task `PENDING` (launcher stopped) in the second project; `fncli second-project-teardown QaTwo`. Start the launcher. Look for the task and its results.

- **Expected:** step 1: the result is `REVOKED` (final), because a deleted link counts as revoked; the results route reads the deleted link on purpose. Step 2: the project is hidden (404); its `PENDING` tasks are never launched and never failed; asking for its results is a 404 and nothing is delivered.
- **Rule:** deleting sets `deleted_at` and `revoked`; a deleted project is hidden ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `webserver/tests/test_results_and_delivery.py` (`test_delivery_of_a_task_in_flight_when_its_link_is_deleted_gives_a_final_revoked_result`, `test_delivery_for_a_deleted_project_is_a_404`), `webserver/tests/test_projects_api.py`. No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Responsibility: the webserver owns the record and the rules; Dagster carries out decisions]: ../decisions/0021-webserver-owns-the-record-and-the-rules.md
[Run keys, retries and the results pull request sync]: ../decisions/0015-run-keys-retries-and-results-pr-sync.md
[docs/architecture/revoke-and-enabled.md#known-limits]: ../../docs/architecture/revoke-and-enabled.md#known-limits
[docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered]: ../../docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered
[docs/architecture/revoke-and-enabled.md#may-a-waiting-task-launch]: ../../docs/architecture/revoke-and-enabled.md#may-a-waiting-task-launch
[docs/architecture/revoke-and-enabled.md#what-each-state-does]: ../../docs/architecture/revoke-and-enabled.md#what-each-state-does
