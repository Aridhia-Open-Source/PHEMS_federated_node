# 0015. Run keys, retries and the results pull request sync

## Context

The state of a results pull request is written by two independent actors: the delivery job (`PUSHED`, `OPENED`) and the sync sensor (`OPENED`, `MERGED`, `CLOSED`), possibly concurrently or late ([0005](0005-state-transition-tables.md)). Everything in Dagster is polling. Dagster keeps run keys per sensor for good: a key that was launched once is never launched again, even if its run failed, so a retry needs a new key.

## Decision

**Sync reconciler.** `results_pull_request_sync_sensor` launches `sync_results_pull_requests_job` when there are `PUSHED` or `OPENED` results and no run of it is in flight (run key `sync-results-prs/<slot>`). The op, per result: `PUSHED` looks up the pull request by branch and records number, url and step if found; `OPENED` fetches it and records `MERGED` or `CLOSED` when changed. A 404 is logged and skipped (not guessed `CLOSED`). The state filter is applied again client-side because a backend that ignored `?state=` would return all results. The repository of a result is resolved by id, through an inactive link too ([0006](0006-global-resources-and-project-links.md)). The sync heals only a pull request that was opened, merged or closed but not recorded.

**State plus slot.** `run_key(kind, item_id, state)` in `sensors/base.py` gives `kind/item_id/state/slot`, with `slot = int(time.time() // retry interval)` (a part that is `None` is left out). A new state gives a new key at once. A failed run with an unchanged state is retried once per retry interval, when the slot moves on.

**The setting** is `DAGSTER_SENSORS_RETRY_INTERVAL_SECONDS` (chart value `fnDagster.sensors.retryIntervalSeconds`, default 60), beside the minimum sensor interval.

**Who uses it.**
- Ingest: `ingest/<repo>/<pr_cursor>/<slot>`.
- Evaluate: `evaluate/<project>/<repo>/<newest UNKNOWN PR number>/<slot>`.
- Results PR sync: `sync-results-prs/<slot>`.
- Delivery retry: `deliver-retry/<result>/<slot>`.

The git and delivery sensors share `LaunchingSensor` ([0014](0014-dagster-pipeline-ops-sensors-and-retries.md)).

**Exactly once.** The launcher (`task/<id>/<attempt>`) and delivery on success (`deliver/<task>/<attempt>`) keep keys without a slot: their run is the only run of that attempt, and a retry bumps the attempt.

**Failed deliveries** are retried by `results_delivery_retry_sensor`: results in state `FAILED` whose step is not final (`OPENED`, `MERGED`, `CLOSED`, `REVOKED`, `STALE`) and whose results link is active (`GET /projects/<pid>/results?state=FAILED&active_link=true`) get `deliver_results_job` again, which resumes from the step reached. A result with `DAGSTER_DELIVERY_MAX_ATTEMPTS` failed attempts (chart value `fnDagster.sensors.deliveryMaxAttempts`, default 5) is not retried any more: it stays `FAILED` until relaunched by hand, by resetting `attempts` with a PATCH or re-running `deliver_results_job`. The key has no attempts, only the slot, so a failing delivery is retried at most once per retry interval.

## Consequences

- A late delivery retry cannot undo what the sync sensor found, and vice versa.
- A retry is never faster than the retry interval, and a new state is acted on at once.
- `CLOSED` is terminal: a pull request reopened on the provider is not followed; one deleted on the provider stays at its last step.
- The exit code is not recorded (the run does not expose it).

## Alternatives considered

- **Webhooks from the provider:** need an inbound route; polling keeps the node outbound-only.
- **Treat a 404 as `CLOSED`:** a transient error could terminate a live delivery.
- **Last-write-wins state:** races between delivery and sync.
