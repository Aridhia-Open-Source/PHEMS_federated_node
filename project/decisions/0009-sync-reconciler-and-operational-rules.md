# 0009. Monotonic PATCH rule, sync reconciler, STOPPED sensors, known limits

- Status: Accepted (the known limits are open). Amended: sync sensor resolves inactive results repository assignments (0019, stage 6).

## Context

The state of a results pull request is written by two independent actors: the delivery job (PUSHED, OPENED) and the sync sensor (OPENED, MERGED, CLOSED), possibly concurrently or late. Everything in Dagster is polling.

## Decision

- **Monotonic PATCH.** `PullRequestResult.set_step` ranks `UNKNOWN < PUSHED < OPENED < MERGED = CLOSED = REVOKED = STALE`. A PATCH may repeat the current step, or move forward; moving backward, or leaving a final step, is a 409 (`InvalidRequest`). A late delivery retry cannot undo what the sync sensor found.
- **Sync reconciler.** `results_pull_request_sync_sensor` launches `sync_results_pull_requests_job` when there are `PUSHED` or `OPENED` results and no run of it is in flight (run key `sync-results-prs/<slot>`, see Run keys and retries). The op, per result: `PUSHED` look up the pull request by branch and record number, url and state if found; `OPENED` fetch it and record `MERGED` or `CLOSED` when changed. A 404 is logged and skipped (not guessed CLOSED). The state filter is applied again client-side because a backend that ignores `?state=` returns all results.
- **Sensors are STOPPED by default** (`default_status=STOPPED`), all of them: the operator starts them (`fncli start-sensor`). Order matters: the run-status sensors only see events after they start, so start them before the launcher or a quick run leaves its task `PENDING`.
- **Task status** is written only by the run-status sensors ([0017](0017-task-status-written-by-run-status-sensors.md)). The backend refuses a move that is not in `TASK_MOVES` with a 409.

## Run keys and retries

The sensors and jobs these keys belong to are in [0023](0023-dagster-pipeline-ops-sensors-and-retries.md).

Dagster keeps run keys per sensor for good: a key that was launched once is never launched again, even if its run failed. So a retry needs a new key.

- **State plus slot.** `run_key(kind, item_id, state)` in `sensors/base.py` gives `kind/item_id/state/slot`, with `slot = int(time.time() // retry interval)` (a part that is `None` is left out). A new state gives a new key at once. A failed run with an unchanged state is retried once per retry interval, when the slot moves on.
- **The setting** is `DAGSTER_SENSORS_RETRY_INTERVAL_SECONDS` (chart value `fnDagster.sensors.retryIntervalSeconds`, default 60), beside the minimum sensor interval.
- **Who uses it.** Ingest: `ingest/<repo>/<pr_cursor>/<slot>`. Evaluate: `evaluate/<project>/<repo>/<newest UNKNOWN PR number>/<slot>`. Results PR sync: `sync-results-prs/<slot>`. Delivery retry: `deliver-retry/<result>/<slot>`. The three git and delivery sensors share `LaunchingSensor`: skip an item with a run in flight, launch the ready ones, log a failing item, and fail the tick only when nothing launched.
- **Exactly once.** The launcher (`task/<id>/<attempt>`) and delivery on success (`deliver/<task>/<attempt>`) keep keys without a slot: their run is the only run of that attempt, and a retry bumps the attempt.
- **Failed deliveries** are retried by `results_delivery_retry_sensor`: results in state `FAILED` whose step is not final (`OPENED`, `MERGED`, `CLOSED`, `REVOKED`, `STALE`) and whose results link is active (`GET /projects/<pid>/results?state=FAILED&active_link=true`) get `deliver_results_job` again, which resumes from the step reached. A result with `DAGSTER_DELIVERY_MAX_ATTEMPTS` failed attempts (chart value `fnDagster.sensors.deliveryMaxAttempts`, default 5) is not retried any more: it stays FAILED until relaunched by hand, by resetting `attempts` with a PATCH or re-running `deliver_results_job`. The key has no attempts, only the slot, so a failing delivery is retried at most once per retry interval.
- **Launcher errors** (e.g. the config GET fails) leave the task `PENDING` and are logged; it is retried on the next tick, and its run key is unused because no run was created. Only the rules fail a task, checked in this order: something it uses is revoked or deleted (the cause starts "revoked: "), the configuration changed, the dataset is not active, the dataset secret is disabled.

## Known limits

- The delivery sensor fires once per task attempt (`run_key = deliver/<task>/<attempt>`); a failed delivery is retried by `results_delivery_retry_sensor` and resumes from its state. The sync sensor heals only a pull request that was opened, merged or closed but not recorded.
- `CLOSED` is terminal: a pull request reopened on the provider is not followed.
- A results pull request deleted on the provider stays at its last state.
- The exit code is not recorded (the run does not expose it).

## Alternatives considered

- **Webhooks from the provider**: needs an inbound route; polling chosen.
- **Treat 404 as CLOSED**: rejected, a transient error could terminate a live delivery.
- **Last-write-wins state**: rejected, races between delivery and sync.
