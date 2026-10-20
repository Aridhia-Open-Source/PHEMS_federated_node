# Task pinning

When a task is created it stores a snapshot of the configuration it was built against: the results repository (id, uri, the GitProvider's `api_uri`, the link's `target_dir`) and the dataset (name, host, port, type, read and write schema). It holds no credentials, no trigger repository and no `enabled` or `revoked` flags. Before launch, and before a result is created, the webserver rebuilds the snapshot from the current state and compares. A task whose setup changed fails at launch, or its result is `STALE` (final, never delivered). Edits to a GlobalResource or a link are always allowed; the cost falls on the work in flight.

Two of the behaviours below (marked in their titles) were removed from the end-to-end suites; all of this section is only unit-tested. That is why it is ranked high in [the index](README.md).

Needs: the dev project with sensors running and no task in flight. Use the two recipes in [the index](README.md): "Make a change while a task is still PENDING" and "Make a change while a task is RUNNING or before delivery". Note the original `target_dir` first (`fncli project-show | jq '.results_links[0].target_dir'`) and put it back at the end of each case.

## The snapshot is recorded at creation and holds no credentials

1. Merge a watched pull request. When the task exists, `GET /projects/<pid>/tasks/<id>/config`.

- **Expected:** `current` is true, `changes` is empty, and `config_snapshot` holds the results repository (id, uri, `api_uri`, `target_dir`) and the dataset (name, host, port, type, read and write schema), plus a `config_hash`. It contains no token, password or Secret value and no `enabled` or `revoked` flags. The request changes nothing (repeat it).
- **Rule:** what the snapshot holds and leaves out ([A task is pinned to its configuration]).
- **Automated by:** Automated: `webserver/tests/test_task_config.py` (`test_build_snapshot_holds_identity_fields_only`, `test_pr_task_is_pinned_at_creation_and_retry_does_not_repin`, `test_asking_for_the_decision_changes_nothing`). They miss a snapshot built from a live node's data.
- [ ] Pass
- [ ] Fail — notes:

## A results link's `target_dir` changed while the task waits fails the task at launch (removed from the end-to-end suites)

1. Recipe: task `PENDING`, launcher stopped.
2. `fncli link-set results --target-dir <another directory>` (a directory that no trigger link watches).
3. `GET /projects/<pid>/tasks/<id>/config`. Start the launcher.
4. Restore the `target_dir`.

- **Expected:** step 2 is accepted (an edit is free). Step 3: `current` is false and `changes` names `target_dir`. The task goes `FAILED` with a cause that names the change (the pinned configuration changed). No run, no result. It stays `FAILED` after step 4.
- **Rule:** a task that is not current is not launched; the webserver fails it with the changes as the cause ([A task is pinned to its configuration]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_config_is_current_then_stale_after_target_dir_changes`, `test_changed_wins_over_the_dataset_link_not_active`), `webserver/tests/test_task_launch.py`. Removed from the end-to-end failure suite. They miss the live launcher.
- [ ] Pass
- [ ] Fail — notes:

## A change that is undone before the launcher looks does not fail the task

1. Recipe: task `PENDING`, launcher stopped.
2. Change the `target_dir`, then change it back to the original.
3. Start the launcher.

- **Expected:** the task launches and runs. The check compares the current state with the snapshot; it has no memory of the change.
- **Rule:** the webserver rebuilds the snapshot from the current state and compares it ([A task is pinned to its configuration]).
- **Automated by:** Manual only. The unit tests change a value and check the diff, not a change that is reverted.
- [ ] Pass
- [ ] Fail — notes:

## A dataset field changed while the task waits fails the task at launch

1. Recipe: task `PENDING`, launcher stopped.
2. `PATCH /global/datasets/<id>` to change a field the snapshot holds (for example `host`; check the body field names).
3. `GET /projects/<pid>/tasks/<id>/config`. Start the launcher. Put the field back.

- **Expected:** `changes` lists the dataset field; the task goes `FAILED` with that cause. No run, no result.
- **Rule:** the dataset's host, port, type and schemas are pinned ([A task is pinned to its configuration]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_dataset_change_makes_the_task_stale`, `test_diff_lists_changed_fields_readably`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A `target_dir` changed after the task succeeded and before delivery leaves the result `STALE` (removed from the end-to-end suites)

1. Merge a watched pull request. While the task is `RUNNING` (preferred), or after `SUCCESS` with the delivery sensors stopped (the recipe and its caution are in [the index](README.md)): `fncli link-set results --target-dir <another directory>`.
2. Wait for the result.
3. Restore the `target_dir`. Wait ten intervals.

- **Expected:** the task is `SUCCESS`. The result is step `STALE`, state `FAILED`, with an error listing the change. Nothing is pushed: no branch, no results pull request. Restoring the `target_dir` delivers nothing; `STALE` is final.
- **Rule:** a `SUCCESS` task whose configuration changed gets a `STALE` result ([A task is pinned to its configuration]; [Polymorphic Result, PullRequestResult, a forward-only step and a separate state]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_post_result_is_stale_when_the_target_dir_changed_after_creation`, `test_post_result_of_a_current_task_is_not_stale`), `webserver/tests/test_results_and_delivery.py` (`test_post_result_stale_beats_switched_off_and_is_final`). Removed from the end-to-end failure suite. They miss the live delivery.
- [ ] Pass
- [ ] Fail — notes:

## A dataset field changed while the task runs leaves the result `STALE`

1. Merge a watched pull request. While the task is `RUNNING`: `PATCH /global/datasets/<id>` to change `host`. Wait for the result.
2. Put the field back.

- **Expected:** the task finishes `SUCCESS` (a running task is not stopped); the result is `STALE` and `FAILED`, never delivered.
- **Rule:** as the previous case, for the dataset ([A task is pinned to its configuration]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_dataset_change_makes_the_task_stale`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## Swapping the project's results repository fails or stales the task

The results link can be replaced only while the project is disabled.

1. Recipe: task `PENDING`, launcher stopped.
2. `fncli project-set --enabled false`. Unlink the results link and link a different ResultsRepository (a scratch one), then `fncli project-set --enabled true`.
3. Start the launcher. Put the original link back the same way afterwards.

- **Expected:** the task goes `FAILED` with a cause that names the changed results repository (its id and uri are pinned). Check the text.
- **Rule:** the results repository's id and uri are in the snapshot; a link swap is a material edit ([A task is pinned to its configuration]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (the diff of added, removed and changed fields). Not tested with a real swap.
- [ ] Pass
- [ ] Fail — notes:

## Changes that are not pinned do not touch tasks in flight

1. Recipe: task `PENDING`, launcher stopped.
2. Change things the snapshot does not hold: the trigger link's `watch_dir` (`PATCH` the link), and a Secret's value (`fncli init-git-secret --entity results` writes a fresh token). The `enabled` and `revoked` flags are not pinned either, but they have their own rules ([enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md)).
3. Start the launcher. Put things back.

- **Expected:** the task launches and runs; `GET .../config` shows `current` true. A credential rotation reaches the running work.
- **Rule:** credentials, the trigger repository and the flags are outside the snapshot so that rotations reach running work and the flags keep their own rules ([A task is pinned to its configuration]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (`test_diff_ignores_version_and_fields_the_stored_snapshot_lacks`, `test_edit_of_target_dir_enabled_and_delete_of_an_enabled_project_with_a_task_in_flight`). No end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## An edit after the result exists changes nothing

1. Run a task to `OPENED`.
2. `fncli link-set results --target-dir <another directory>`. Wait for two sync intervals. Restore.

- **Expected:** the result stays `OPENED`; the results pull request and branch are untouched; the sync sensor goes on recording its state. The result's repository and directory came from the snapshot, not from the link.
- **Rule:** at delivery the results repository id and `target_dir` come from the snapshot, so an edited link does not redirect a push ([A task is pinned to its configuration]). An existing non-final result is re-checked only for a revoke (check that an edit does not change it) ([docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (`test_delivery_takes_the_target_dir_from_the_pinned_configuration_and_reads_no_link`); no test edits the link after the result exists.
- [ ] Pass
- [ ] Fail — notes:

## A stale or failed task has no automatic retry

1. After the `FAILED` or `STALE` cases above, look at the pull request and the task.

- **Expected:** the pull request stays `YIELDED`; no new task is made for it; nothing re-runs it. To process the change again a new pull request is needed. Retrying a task is on hold until after the beta.
- **Rule:** there is no stale-task retry; a stale task fails and the pull request has to be re-run another way ([A task is pinned to its configuration]; [State transition tables for triggers, tasks and result steps; 409 on a refused move]).
- **Automated by:** Partly automated: `webserver/tests/test_pull_requests_and_tasks.py` (`test_retry_resets_a_failed_task_only`). See [permissions and out of scope](permissions-and-out-of-scope.md).
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[A task is pinned to its configuration]: ../decisions/0009-task-pinned-to-its-configuration.md
[Polymorphic Result, PullRequestResult, a forward-only step and a separate state]: ../decisions/0004-polymorphic-result-and-forward-only-state.md
[State transition tables for triggers, tasks and result steps; 409 on a refused move]: ../decisions/0005-state-transition-tables.md
[docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered]: ../../docs/architecture/revoke-and-enabled.md#may-a-finished-tasks-result-be-delivered
