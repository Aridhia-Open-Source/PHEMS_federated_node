# Sensors, restarts and catch-up

**Manual only, and important.** The end-to-end suites no longer stop or start sensors, and the scenarios that did were removed. Every case in this section is therefore checked by hand or not at all. The unit tests mock the Dagster instance, so they cannot show a restart, a stopped sensor or catch-up.

What is supposed to hold:

- The pipeline is polling and level-triggered: ingest reads the git provider from a cursor, evaluate and the launcher read the webserver's state every tick, the reconcile sensor reads each unfinished task's run every tick. Nothing in them is a queue, so downtime should delay work, not lose it.
- A run key that was launched is never launched again, so a restart should not duplicate runs ([Run keys, retries and the results pull request sync]).
- The start order of the sensors does not matter; the reconcile sensor sets a task whose event was missed to the status of its run ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- One caveat from the same decision: a run-status sensor only sees events from when it starts. That includes `task_results_delivery_sensor`, which launches the first delivery when a task run succeeds. Where a case below touches it, the sources do not say what happens; the case says "check".

Needs: the dev project with sensors running, `fncli`, `kubectl`, the Dagster UI. Take counts (see [the index](README.md)) before and after. If a case leaves a task `PENDING`, a result missing or a pull request without a trigger, record it as a finding with `fncli sensor-status` and the pod logs.

## Restarting the ingest sensor does not duplicate pull requests or tasks (removed from the end-to-end suites)

1. Run two watched pull requests to completion. Note the counts.
2. Three times: `fncli stop-sensor --sensor ingest`, wait two intervals, `fncli start-sensor --sensor ingest`, wait two intervals.
3. Note the counts. `fncli link-set trigger --revoked true`, then `--revoked false`. Stop and start the ingest sensor once more. Note the counts.
4. Merge one watched pull request.

- **Expected:** counts unchanged after step 2 and after step 3 (the pull requests are stored once; no second trigger, no second task). After step 4 exactly one more pull request, trigger and task.
- **Rule:** posting the same pull requests again changes nothing; one task per trigger ([Pull requests stored once per repository, fanned out to project links, with cursors]; [Polymorphic Trigger with PullRequestTrigger and ApiRequestTrigger]).
- **Automated by:** Manual only (removed from the end-to-end failure suite). `webserver/tests/test_pull_requests_and_tasks.py` shows the store is idempotent; it cannot restart a sensor.
- [ ] Pass
- [ ] Fail — notes:

## Sensors that were all stopped while a pull request was merged catch up when started (removed from the end-to-end suites)

1. `fncli stop-sensor --sensor all`. `fncli sensor-status` (all stopped). Note the counts.
2. `fncli open-pr --kind watched --merge`. Wait three intervals. Note the counts.
3. `fncli start-sensor --sensor all`. Watch `fncli project-show` for several intervals.

- **Expected:** step 2: nothing changes (no sensor is running). After step 3 the pull request is stored, gets one trigger (`UNKNOWN`, then `YIELDED`) and one task, and the task is launched, runs and its result is delivered. No task stays `PENDING`. Counts end exactly one higher in pull requests and tasks.
- **Rule:** polling from a cursor loses nothing while the sensors are down ([Pull requests stored once per repository, fanned out to project links, with cursors]; [The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Manual only (removed from the end-to-end failure suite).
- [ ] Pass
- [ ] Fail — notes:

## Several pull requests merged while ingest was stopped are all picked up, once, in order

1. `fncli stop-sensor --sensor ingest`. Note the counts.
2. Merge three watched pull requests one after another.
3. `fncli start-sensor --sensor ingest`. Wait.

- **Expected:** the three pull requests are stored and get one trigger each (stored count up by three, pull requests up by three), then three tasks (one per pull request). Look at the order in `fncli project-show`: triggers follow the merge order (the cursor is the pair merge time and number).
- **Rule:** the global cursor is the latest stored `merged_at`; a link's cursor orders by `(merged_at, number)` ([Pull requests stored once per repository, fanned out to project links, with cursors]).
- **Automated by:** Partly automated: `dagster/app/tests/test_ingest_job.py` (oldest first) and `webserver/tests/test_pull_requests_and_tasks.py` (cursor tests). A real sensor catching up is not tested.
- [ ] Pass
- [ ] Fail — notes:

## With evaluate stopped, a pull request waits `UNKNOWN`; with the launcher stopped, a task waits `PENDING`; both resume once

1. `fncli stop-sensor --sensor evaluate`. Merge a watched pull request. Wait three intervals: the pull request should be `UNKNOWN` with no task. `fncli start-sensor --sensor evaluate`.
2. `fncli stop-sensor --sensor launcher`. Merge another. Wait for its task to be `PENDING`, then three more intervals. `fncli start-sensor --sensor launcher`.

- **Expected:** step 1: after the start the pull request is `YIELDED` with one task. Step 2: the task stays `PENDING` while the launcher is stopped, then launches once (one run with key `task/<id>/<attempt>` in the Dagster UI) and finishes.
- **Rule:** the sensors are independent and level-triggered; the run key makes a repeated request a no-op ([Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: `dagster/app/tests/test_pr_evaluate_sensor.py`, `dagster/app/tests/test_task_launcher.py` (`test_the_launcher_patches_nothing_and_re_yields_the_same_run_key`); they do not stop a live sensor.
- [ ] Pass
- [ ] Fail — notes:

## The sensors can be started in any order

1. `fncli stop-sensor --sensor all`.
2. Start them one group at a time in an odd order: `launcher`, then `status`, then `delivery`, then `evaluate`, then `ingest` (`fncli start-sensor --sensor <name>` each).
3. `fncli open-pr --kind watched --merge` and follow it through to a results pull request.
4. Repeat steps 1 to 3 with the reverse order.

- **Expected:** the same path as with `--sensor all`, with no task stuck and no failed tick.
- **Rule:** the start order does not matter ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Manual only (the end-to-end suites start nothing).
- [ ] Pass
- [ ] Fail — notes:

## A task that finished while the run-status sensors were stopped gets its final status when they start

This is one of the [checks that have never run on a cluster](../TESTING.md#checks-that-have-never-run-on-a-cluster).

1. In the Dagster UI switch off the five run-status sensors and `task_reconcile_sensor` (`fncli stop-sensor --sensor status` stops all six). Leave ingest, evaluate and launcher on.
2. Merge a watched pull request. Let the task's run finish in the Dagster UI. Look at the task: it is not `SUCCESS` yet (it may be `PENDING`).
3. `fncli start-sensor --sensor status`. Watch the task and the reconcile sensor's ticks in the Dagster UI.

- **Expected:** within about an interval of starting, the task is `SUCCESS` (or `FAILED`), with `executor_run_id`, `started_at` and `completed_at`. The reconcile sensor's tick shows how many tasks it patched. No duplicate patches on the next tick.
- **Rule:** the reconcile sensor sets every unfinished task to the status of its run each tick ([Task status is written by the run-status sensors and the reconcile sensor]; [docs/architecture/sensors/task-reconcile.md]).
- **Automated by:** Manual only for the live behaviour. `dagster/app/tests/test_task_reconcile_sensor.py` tests a fake instance and one real instance, never real runs ([TESTING.md](../TESTING.md#checks-that-have-never-run-on-a-cluster)).
- [ ] Pass
- [ ] Fail — notes:

## A task that succeeded while the delivery sensors were stopped: is its result ever delivered?

Check, and record the outcome as a finding if the result never appears.

1. `fncli stop-sensor --sensor delivery`. Merge a watched pull request. Wait until the task is `SUCCESS`; no result exists.
2. `fncli start-sensor --sensor delivery`. Wait ten intervals. `fncli project-show`.

- **Expected:** the sources do not say. The first delivery is launched by the success sensor, a run-status sensor that sees events from when it starts, and the retry sensor only handles results that already exist as `FAILED`. If no result appears, the task is `SUCCESS` with no delivery and nothing will retry it: record it. If a result appears, record which sensor launched it (Dagster UI, run tags).
- **Rule:** a run-status sensor only sees events from when it starts; the retry sensor lists `FAILED` results ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]; [Run keys, retries and the results pull request sync]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

## A results pull request merged while the sync sensor was stopped is recorded when it starts

1. Run a task to `OPENED`. `fncli stop-sensor --sensor delivery`.
2. `fncli merge-results-pr --number <n>`. Wait three intervals: the result is still `OPENED`.
3. `fncli start-sensor --sensor delivery`.

- **Expected:** within a sync interval the result is `MERGED`, with the merge fields.
- **Rule:** each sync run reads the `PUSHED` and `OPENED` results again, so a result is checked until it is merged or closed ([Run keys, retries and the results pull request sync]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_pull_request_sync.py`. No stopped sensor on a live node.
- [ ] Pass
- [ ] Fail — notes:

## Restarting the Dagster code server mid-flow

1. Merge a watched pull request. While the task is `RUNNING`, restart the code server: `kubectl rollout restart deployment/<the code server deployment>` (name: check with `kubectl get deploy -A`). Wait for it to be ready.
2. `fncli sensor-status`.
3. Start any sensor that is stopped (`fncli start-sensor --sensor all`). Follow the task and delivery.

- **Expected:** the task's run, a separate pod, is not killed and finishes. The end-to-end notes say a code server restart stops the sensors, so some or all may show `STOPPED` in step 2: record which. After step 3 the task reaches its final status, its result is delivered (check, see the caution in the case above on delivery) and no task or pull request is duplicated.
- **Rule:** sensors default to stopped; run keys prevent duplicates ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

## Restarting the Dagster daemon while idle and while a task runs

1. With the sensors running and no task in flight: delete the daemon pod and wait for it to return. Check that ticks resume and `fncli sensor-status` shows the sensors still running.
2. Merge a watched pull request. While the task is `RUNNING`, delete the daemon pod again. Wait.

- **Expected:** step 1: sensors keep their running status and tick again. Step 2: the task finishes and its status is recorded; no duplicate run for the task or the delivery (Dagster Runs page: one run per run key).
- **Rule:** sensors keep no state of their own; the state is in the webserver and in Dagster ([docs/architecture/sensors/README.md]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

## The whole node restarted with work in flight

1. Leave one task `RUNNING`, one task `PENDING` (stop the launcher to hold it), one result `OPENED` (not merged) and one pull request stored but not yet evaluated (stop evaluate to hold it).
2. Restart every pod in the release namespace, or restart the cluster node. Wait until everything is ready.
3. `fncli sensor-status`, `fncli start-sensor --sensor all` if needed. Follow each item.

- **Expected:** each item resumes from where it was: the running task ends in a final status; the pending task launches once; the opened result can still be merged and recorded; the stored pull request gets one trigger and task. Nothing is duplicated and nothing is stuck. Record any item that does not recover.
- **Rule:** the state is in the webserver's database and Dagster's run storage, not in the sensors ([docs/architecture/sensors/README.md]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[Polymorphic Trigger with PullRequestTrigger and ApiRequestTrigger]: ../decisions/0001-polymorphic-triggers.md
[Pull requests stored once per repository, fanned out to project links, with cursors]: ../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md
[Run keys, retries and the results pull request sync]: ../decisions/0015-run-keys-retries-and-results-pr-sync.md
[Task status is written by the run-status sensors and the reconcile sensor]: ../decisions/0003-task-status-written-by-run-status-sensors.md
[The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]: ../decisions/0014-dagster-pipeline-ops-sensors-and-retries.md
[docs/architecture/sensors/README.md]: ../../docs/architecture/sensors/README.md
[docs/architecture/sensors/task-reconcile.md]: ../../docs/architecture/sensors/task-reconcile.md
