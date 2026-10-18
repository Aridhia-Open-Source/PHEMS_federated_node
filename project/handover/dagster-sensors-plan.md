# Plan: Dagster sensor redesign and the Dagster changes the global-resources work needs

Branch `moonshot/dagster-sensors`, based on `moonshot/shared-resources`. A plan only: no code changed. The Dagster unit tests have
never been run (the `dagster` package is missing in the cloud sandbox), so step 0 is to run them.

## Sensors today (10)

| Group | Sensor | Job |
|---|---|---|
| git | ingest | polls each active trigger repo for merged PRs, POSTs them to the webserver |
| git | evaluate | parses UNKNOWN PRs, creates the task (or REJECTED), yields an evaluate run |
| task | launcher | starts a run for each PENDING task |
| task | 5 run-status sensors | copy Dagster run status back to the task |
| task | results delivery | pushes a finished task's results and opens the results PR |
| task | results PR sync | updates the result row when the results PR is merged or closed |

Minimum interval 10 s (`MIN_SENSOR_INTERVAL_SECONDS`).

## Proposed (about 4 groups)

- **Mirror webhook replaces ingest polling.** The webserver receives the Gitea-mirror webhook and stores the PR; a slow ingest poll
  stays as the fallback. Depends on the Gitea mirror (ADR 0020).
- **One per-PR job** (evaluate, create task, run), started by one sensor or the webhook, keyed by `run_key` so a PR runs once.
  This replaces the evaluate sensor and the launcher.
- **Delivery becomes the last op of the task job**, so the delivery sensor goes away.
- **The five run-status sensors stay**, counted as one group.
- **Results PR sync stays** as a sensor.

## Dagster changes needed whether or not the redesign happens

1. Ingest: send at most 100 PRs per batch, and isolate errors per repo (a bad token or a repo with more than 100 PRs behind the
   cursor wedges every repo today).
2. Treat the new 409s as "skip, not error": task through an inactive link, status change of a finished task, result through an
   inactive link, result for a task that is not SUCCESS.
3. Push filtering to the webserver instead of Python: project `enabled` and `locked`, PR `task_id`, cross-project results `step`.
   Touches `launcher.py`, `pr_evaluate.py`, `delivery/results.py`, `pull_request_sync.py` and the fncli `find_*` helpers.
   `GET /projects?enabled=true` is untested and `parse_query_params` has no boolean coercion, so check that first.
4. Delivery with no results link must record a failed result, not silently skip.
5. Respect a disabled or revoked secret before using its token (today the K8s secret is read unchecked).
6. Narrow the Dagster secret RBAC; restart the code server after a credential rotation (the password is patched but nothing restarts it).
7. Fix `dagster/app/tests/test_pr_ingest_sensor.py` (`active_only=True` is stale) and get the Dagster tests running in CI.

## Order

0. Install `dagster`, run the existing unit tests, fix what is stale.
1. Items 1 to 5 above (small, independent, no design risk).
2. Item 6 (chart change).
3. The redesign (per-PR job, delivery op), once the mirror webhook exists. Write an ADR first.

## Already done on `moonshot/shared-resources`

`IGNORED` removed from the Dagster `TriggerState` and parser (a PR with no watched file parses as REJECTED); the evaluate sensor
calls the link list with `active=True` (`?active=true`); nothing else in Dagster changed.

## Open questions

- Webhook or poll-only for the first cut of the redesign?
- Is the five-sensor run-status group worth replacing with run-status hooks on the job itself?
