# Task and result state machines

Three things only move one way: a trigger (`UNKNOWN` to `YIELDED` or `REJECTED`, both final), a task (`PENDING`, `QUEUED`, `RUNNING`, then `SUCCESS`, `FAILED` or `CANCELED`, all final) and a result's step (`UNKNOWN`, `PUSHED`, `OPENED`, then `MERGED`, `CLOSED`, `REVOKED` or `STALE`, all final and of equal rank). A result's state (`IN_PROGRESS`, `DELIVERED`, `FAILED`) is separate, so a failure never loses how far delivery got. The webserver refuses any other move with a 409, so a late or racing write cannot undo a final state. The task's status and the delivery are independent: a task is `SUCCESS` whether or not its results were delivered.

The unit tests check every pair. These cases check the live pipeline: the sensors that write the states, the retries, and the reconcile sensor that repairs a missed event. Retrying a task is on hold for the beta ([permissions and out of scope](permissions-and-out-of-scope.md)).

Needs: the dev project with sensors running; an administrator token for the API calls. The API calls below use bodies from the route tests; check field names against the route if a call is refused as invalid.

## A finished task cannot be changed to another status

1. Take a task that is `SUCCESS`. `PATCH /projects/<pid>/tasks/<id>` with `{"status": "RUNNING"}`.
2. Take a `FAILED` task and send `{"status": "SUCCESS"}`.
3. Send `{"status": "BOGUS"}`.

- **Expected:** steps 1 and 2 are 409 and the task is unchanged. Step 3 is 400. The pull request stays `YIELDED` whatever the task's status.
- **Rule:** the task table is forward only; the only way out of a final status is a retry ([State transition tables for triggers, tasks and result steps; 409 on a refused move]).
- **Automated by:** Automated: `webserver/tests/test_state_rules.py`, `webserver/tests/test_pull_requests_and_tasks.py` (`test_finished_tasks_cannot_change_status`, `test_bad_task_patches_are_400_and_change_nothing`, `test_patching_a_pr_task_status_leaves_the_trigger_yielded`). Real sensors racing the API are not tested.
- [ ] Pass
- [ ] Fail — notes:

## A trigger's final states cannot be moved, and a task cannot be made from them

1. Take a `REJECTED` trigger (see [failure paths](failure-paths.md)). `PATCH /projects/<pid>/repositories/triggers/<id>/pull_requests/<number>` with `{"state": "UNKNOWN"}`, then with `{"state": "YIELDED"}`.
2. `POST .../pull_requests/<number>/task` for that pull request.
3. Do the same for a `YIELDED` trigger.
4. `PATCH` with `{"state": "REJECTED"}` and no `state_cause`.

- **Expected:** steps 1 to 3 are 409 and nothing changes. Step 4 is 400 (a cause is required for `REJECTED`).
- **Rule:** `YIELDED` and `REJECTED` have no moves; a task is made only from an `UNKNOWN` trigger of an active project resource ([State transition tables for triggers, tasks and result steps; 409 on a refused move]).
- **Automated by:** Automated: `webserver/tests/test_state_rules.py`, `webserver/tests/test_pull_requests_and_tasks.py` (`test_patch_state_unknown_to_yielded_is_final`, `test_rejected_trigger_cannot_go_back_to_unknown`, `test_only_unknown_triggers_of_an_active_resource_get_a_task`). It misses a live node.
- [ ] Pass
- [ ] Fail — notes:

## A result's step only moves forward and the final steps do not move

1. Take a result at `OPENED`. `PATCH /projects/<pid>/results/<id>` with `{"step": "PUSHED"}`.
2. Take a `MERGED` result and send `{"step": "CLOSED"}`, then `{"step": "OPENED"}`.
3. Take a `REVOKED` or `STALE` result and send `{"step": "OPENED"}`.
4. Send `{"state": "FAILED"}` to an `OPENED` result and look at its step.

- **Expected:** steps 1 to 3 are 409 and nothing changes. Step 4 is accepted and the step is unchanged (a failure sets the state, not the step).
- **Rule:** the step is forward only; `MERGED`, `CLOSED`, `REVOKED` and `STALE` are final and of equal rank; the state is separate ([Polymorphic Result, PullRequestResult, a forward-only step and a separate state]; [State transition tables for triggers, tasks and result steps; 409 on a refused move]).
- **Automated by:** Automated: `webserver/tests/test_state_rules.py`, `webserver/tests/test_results_and_delivery.py` (`test_step_is_forward_only`, `test_patching_a_result_to_failed_leaves_its_step_alone`). A late delivery retry racing the sync sensor cannot be timed by hand.
- [ ] Pass
- [ ] Fail — notes:

## The reconcile sensor repairs a task status that the run-status sensors missed

fncli stops the reconcile sensor together with the run-status sensors (`--group status`), so use the Dagster UI.

1. In the Dagster UI, Automation, switch off `task_queued_sensor`, `task_started_sensor`, `task_success_sensor`, `task_failure_sensor` and `task_canceled_sensor`. Leave `task_reconcile_sensor` and `task_results_delivery_sensor` on.
2. `fncli open-pr --kind watched --merge`. Watch the task.
3. Switch the five sensors back on.

- **Expected:** the task still reaches `QUEUED`/`RUNNING` and `SUCCESS` (written by the reconcile sensor from the run's current status, with `executor_run_id`, `started_at` and `completed_at` from the run record), and delivery still starts. The reconcile sensor's ticks show a skip reason that counts the tasks it patched. No tick fails. Check how long the status lags; it should be about one interval.
- **Rule:** the reconcile sensor sets every unfinished task to the status of its run each tick, so a missed event is repaired ([Task status is written by the run-status sensors and the reconcile sensor]; [docs/architecture/sensors/task-reconcile.md]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_reconcile_sensor.py` (a fake instance and one real instance); it has never run against a live Dagster with real runs ([TESTING.md](../TESTING.md#checks-that-have-never-run-on-a-cluster)). No end-to-end test.
- [ ] Pass
- [ ] Fail — notes:

## The reconcile sensor leaves a disabled project's tasks alone, and repairs them once enabled

1. As above, with the five run-status sensors off. Merge a watched pull request. When the task is `RUNNING`, `fncli project-set --enabled false`.
2. Wait for the run to finish in the Dagster UI. Wait three intervals. Look at the task.
3. `fncli project-set --enabled true`. Switch the five sensors back on.

- **Expected:** while the project is disabled the task is not patched and stays `RUNNING` although the run finished. After step 3 the reconcile sensor sets it `SUCCESS`.
- **Rule:** the reconcile sensor looks only at the tasks of enabled projects ([docs/architecture/sensors/task-reconcile.md]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_reconcile_sensor.py` (`test_a_task_of_a_disabled_project_is_not_touched`). The run-status sensors act on any project, so with them on you will not see this.
- [ ] Pass
- [ ] Fail — notes:

## A run canceled in Dagster ends the task `CANCELED` with no result

1. Merge a watched pull request with a task that takes long enough. In the Dagster UI terminate its `k8s_pipes_job` run.
2. Watch the task for several intervals.

- **Expected:** the task goes `CANCELED` and stays there; no result is made; the pull request stays `YIELDED`. The webserver has no cancel route of its own (cancel is not implemented there).
- **Rule:** the task status mirrors the run's; `CANCELED` is final ([Task status is written by the run-status sensors and the reconcile sensor]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_run_status_sensor.py` (the mapping, including canceled); `webserver/tests/test_pull_requests_and_tasks.py` (`test_cancel_is_not_implemented_and_leaves_the_task_alone`). No test cancels a live run.
- [ ] Pass
- [ ] Fail — notes:

## A held result is retried at most once per retry interval and delivered when the cause goes

1. Hold a result: merge a watched pull request, `fncli resource-set results --enabled false` while it runs, wait until the result is `UNKNOWN` and `FAILED`.
2. In the Dagster UI watch `results_delivery_retry_sensor` for several intervals with the project resource still off.
3. `fncli resource-set results --enabled true`.

- **Expected:** step 2: the sensor does not launch a delivery (the project resource is not active), so there are no `deliver-retry` runs. Step 3: one delivery run starts (run key `deliver-retry/<result>/<slot>`) and the result goes `OPENED`, `DELIVERED`; the run is not repeated.
- **Rule:** the retry sensor lists `FAILED` results at a non-final step on an active project resource; the run key carries a slot so a failing delivery is retried at most once per interval ([Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "work in flight: a results resource switched off before delivery is held FAILED, delivered once the resource is on" (written, never run on a cluster); `dagster/app/tests/test_results_delivery.py` (the retry sensor tests). It does not look at the run keys.
- [ ] Pass
- [ ] Fail — notes:

## A delivery that keeps failing stops after the maximum attempts, with no alert

Takes several retry intervals (60 seconds each by default; five attempts by default).

1. Merge a watched pull request. While the task runs: `fncli delete-gitea-token --entity results` (the results token is lost).
2. Wait for the result. Watch `fncli project-show` results and the Dagster UI for `deliver-retry` runs, for at least six retry intervals. Note `attempts` (`GET /projects/<pid>/results/<id>`).
3. `fncli init-git-secret --entity results` and `fncli verify-git-secret --entity results`. Wait three more intervals.

- **Expected:** the result is `FAILED` with an error each attempt, its step unchanged, `attempts` going up by one per try, one try per retry interval at most. After the maximum (five by default) the sensor stops launching. The task stays `SUCCESS`. After step 3 the result is still not delivered on its own: it stays `FAILED` until `attempts` is reset by hand (`PATCH` the result) or the delivery job is run again. Nothing alerts anyone.
- **Rule:** a delivery with the maximum failed attempts is not retried; it stays `FAILED` until relaunched by hand ([Run keys, retries and the results pull request sync]). The missing alert is an open question in [Enabled, revoked and soft delete].
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (`test_the_retry_sensor_gives_up_at_the_max_attempts`, `test_the_retry_run_key_does_not_change_with_the_attempts`). No end-to-end test; the real timing and the manual reset are untested.
- [ ] Pass
- [ ] Fail — notes:

## A delivery recovers if the token is restored within the attempts

1. As in the previous case, but restore the token (`fncli init-git-secret --entity results`) after the first or second failed attempt.

- **Expected:** the next retry delivers: the branch is pushed, the pull request opened, step `OPENED`, state `DELIVERED`, `error` cleared, `attempts` counted. Exactly one results pull request.
- **Rule:** the retry resumes from the step reached and clears the error on success ([Results delivered as a pushed branch plus a results pull request]; [Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (`test_a_retry_after_a_failure_delivers_and_counts_the_attempt`); it misses a real provider and the token lifecycle.
- [ ] Pass
- [ ] Fail — notes:

## A task and its delivery stay independent

1. In any case where the delivery fails, look at the task.

- **Expected:** the task is `SUCCESS`; delivery never changes the task's status. A failed run of the delivery job is not mirrored onto the task.
- **Rule:** delivery never writes the task status ([Task status is written by the run-status sensors and the reconcile sensor]).
- **Automated by:** Partly automated: `dagster/app/tests/test_task_run_status_sensor.py` (`test_a_failed_delivery_run_never_patches_the_task`, `test_registered_sensors_ignore_delivery_runs`). They miss a real failed delivery run.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Polymorphic Result, PullRequestResult, a forward-only step and a separate state]: ../decisions/0004-polymorphic-result-and-forward-only-state.md
[Results delivered as a pushed branch plus a results pull request]: ../decisions/0013-results-delivered-as-branch-and-pull-request.md
[Run keys, retries and the results pull request sync]: ../decisions/0015-run-keys-retries-and-results-pr-sync.md
[State transition tables for triggers, tasks and result steps; 409 on a refused move]: ../decisions/0005-state-transition-tables.md
[Task status is written by the run-status sensors and the reconcile sensor]: ../decisions/0003-task-status-written-by-run-status-sensors.md
[docs/architecture/sensors/task-reconcile.md]: ../../docs/architecture/sensors/task-reconcile.md
