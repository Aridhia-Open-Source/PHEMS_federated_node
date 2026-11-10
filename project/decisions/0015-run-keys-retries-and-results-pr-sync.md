# 0015. Run keys, retries and the results pull request sync

## Context

A result has two independent writers: the delivery job (`PUSHED`, with `state` `DELIVERED`) and the results pull request sensor (`OPENED`, `MERGED`, `CLOSED`), possibly concurrently or late ([0005](0005-state-transition-tables.md)). `state` is written by delivery only: `DELIVERED` as soon as the branch is pushed, `FAILED` for a failed push. `step` is the pull request's progress. Everything in Dagster is polling. Dagster keeps run keys per sensor for good: a key that was launched once is never launched again, even if its run failed, so a retry needs a new key.

## Decision

**Results pull request sensor.** Delivery stops at the push: the result is `PUSHED` and `DELIVERED`, with `attempts` and `error` reset. `results_pull_request_sync_sensor` opens the pull request and tracks it. Per results repository per tick it reads the provider once, with one token: the pull requests of any state updated since the repository's oldest `PUSHED` or `OPENED` result (`get_pulls`), whatever the number of results. It launches a run per result, unless a run of either job for that result is in flight (run keys `sync-result/<result>/<step>/<slot>` and `open-result/<result>/OPENED/<slot>`, step being the one the result moves to):
- `PUSHED`: the pull request from the result's branch into the task's pinned base branch is in the list: `sync_results_pull_requests_job` records its number, url and step. It is not: `open_results_pull_request_job` creates it and records the same.
- `OPENED`: found by number and `MERGED` or `CLOSED`: `sync_results_pull_requests_job` records the step. Not in the list: logged and skipped (not guessed `CLOSED`).

A result with no change gets no run, so an open pull request starts no pod. The sync run only patches the result with what the sensor found (run config). A failed opening records the error and one more attempt, keeps the state `DELIVERED` and raises, so `results_delivery_retry_sensor`, which takes `FAILED` only, leaves the result alone; the sensor launches the opening again once per retry interval, until `DAGSTER_DELIVERY_MAX_ATTEMPTS`. The backend filters the results by step; the sensor does not filter them again by state. The repository of a result is resolved by id, through an inactive project resource too ([0006](0006-global-resources-and-project-resources.md)).

**Push-only.** The results repository assignment has `open_pull_requests` (default true). With false, `GET /projects/<pid>/results?step=PUSHED&open_pull_requests=true` leaves that project's results out, so they stay `PUSHED`, and `OPENED` results are tracked whatever it says. A node that wants push-only for every project stops the sensor in Dagster.

**State plus slot.** `run_key(kind, item_id, state)` in `sensors/base.py` gives `kind/item_id/state/slot`, with `slot = int(time.time() // retry interval)` (a part that is `None` is left out). A new state gives a new key at once. A failed run with an unchanged state is retried once per retry interval, when the slot moves on.

**The setting** is `DAGSTER_SENSORS_RETRY_INTERVAL_SECONDS` (chart value `fnDagster.sensors.retryIntervalSeconds`, default 60), beside the minimum sensor interval.

**Who uses it.**
- Ingest: `ingest/<repo>/<pr_cursor>/<slot>`.
- Evaluate: `evaluate/<project>/<repo>/<newest UNKNOWN PR number>/<slot>`.
- Results PR sensor: `sync-result/<result>/<step>/<slot>` and `open-result/<result>/OPENED/<slot>`.
- Delivery retry: `deliver-retry/<result>/<slot>`.

The git and delivery sensors share `LaunchingSensor` ([0014](0014-dagster-pipeline-ops-sensors-and-retries.md)).

**Exactly once.** The launcher (`task/<id>/<attempt>`) and delivery on success (`deliver/<task>/<attempt>`) keep keys without a slot: their run is the only run of that attempt, and a retry bumps the attempt.

**Failed deliveries** are retried by `results_delivery_retry_sensor`: results in state `FAILED` whose step is not final (`PUSHED`, `OPENED`, `MERGED`, `CLOSED`, `REVOKED`, `STALE`) and whose results resource is active (`GET /projects/<pid>/results?state=FAILED&active_resource=true`) get `deliver_results_job` again, which does not push a branch already on the remote. A result with `DAGSTER_DELIVERY_MAX_ATTEMPTS` failed attempts (chart value `fnDagster.sensors.deliveryMaxAttempts`, default 5) is not retried any more: it stays `FAILED` until relaunched by hand, by resetting `attempts` with a PATCH or re-running `deliver_results_job`. The key has no attempts, only the slot, so a failing delivery is retried at most once per retry interval.

## Consequences

- A late delivery retry cannot undo what the sensor found, and vice versa.
- `DELIVERED` means pushed, not that a pull request exists. With the sensor off, or a project push-only, a result stays `PUSHED` and `DELIVERED`.
- The provider list reaches back to the oldest result still tracked, so a pull request left open for long makes every tick page further.
- A retry is never faster than the retry interval, and a new state is acted on at once.
- `CLOSED` is terminal: a pull request reopened on the provider is not followed; one deleted on the provider stays at its last step.
- The exit code is not recorded (the run does not expose it).

## Alternatives considered

- **Webhooks from the provider:** need an inbound route; polling keeps the node outbound-only.
- **Treat a 404 as `CLOSED`:** a transient error could terminate a live delivery.
- **Last-write-wins state:** races between delivery and the sensor.
- **Delivery opens the pull request, as before:** a provider outage after the push failed the delivery, and each result cost its own provider calls.
- **One provider call per result:** the calls grow with the results; one list per repository does not.
