# 0009. Monotonic PATCH rule, sync reconciler, STOPPED sensors, known limits

- Status: Accepted (the known limits are open)

## Context

The state of a results pull request is written by two independent actors: the delivery job (PUSHED, OPENED) and the sync sensor (OPENED, MERGED, CLOSED), possibly concurrently or late. Everything in Dagster is polling.

## Decision

- **Monotonic PATCH.** `PullRequestResult.set_state` ranks `UNKNOWN < PUSHED < OPENED < MERGED = CLOSED`. A PATCH may repeat the current state, or move forward; moving backward, or leaving MERGED or CLOSED, is a 400 (`InvalidRequest`). A late delivery retry cannot undo what the sync sensor found.
- **Sync reconciler.** `results_pull_request_sync_sensor` launches `sync_results_pull_requests_job` when there are `PUSHED` or `OPENED` results and no run of it is in flight (run key per minute). The op, per result: `PUSHED` look up the pull request by branch and record number, url and state if found; `OPENED` fetch it and record `MERGED` or `CLOSED` when changed. A 404 is logged and skipped (not guessed CLOSED). The state filter is applied again client-side because a backend that ignores `?state=` returns all results.
- **Sensors are STOPPED by default** (`default_status=STOPPED`), all of them: the operator starts them (`fncli start-sensor`). Order matters: the run-status sensors only see events after they start, so start them before the launcher or a quick run leaves its task `PENDING`.
- **Task status** is written only by the run-status sensors ([0017](0017-task-status-written-by-run-status-sensors.md)).

## Known limits

- No automatic delivery retry: the delivery sensor fires once per task attempt (`run_key = deliver/<task>/<attempt>`). A failed delivery is re-launched by hand and resumes from its state. The sync sensor heals only a pull request that was opened, merged or closed but not recorded.
- `CLOSED` is terminal: a pull request reopened on the provider is not followed.
- A results pull request deleted on the provider stays at its last state.
- Task PATCH does not enforce an order (it trusts the run-status sensors).
- The exit code is not recorded (the run does not expose it).

## Alternatives considered

- **Webhooks from the provider**: needs an inbound route; polling chosen.
- **Treat 404 as CLOSED**: rejected, a transient error could terminate a live delivery.
- **Last-write-wins state**: rejected, races between delivery and sync.
