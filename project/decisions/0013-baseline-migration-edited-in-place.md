# 0013. Baseline migration edited in place while the schema is not live

- Status: Provisional (until a deployment holds data worth keeping)

## Context

The schema was redesigned several times (task requests, triggers, results, secrets, repositories). No environment keeps data across these changes.

## Decision

There is a single Alembic revision, `001_baseline` (`webserver/migrations/versions/001_baseline.py`), edited in place for every schema change instead of stacking revisions. `projects.default_dataset_id` is added after `datasets` to close the cycle, and the downgrade drops tables in reverse order. Environments are rebuilt (the dev loop tears down and redeploys) to pick up a change. The Dagster database has its own, unrelated schema.

## Consequences

- A clean history for the first release, no migration chains to untangle.
- Any environment created from an older baseline must be recreated; there is no upgrade path between baseline versions.
- This must stop at the first deployment with data to keep; then new revisions are added and `001_baseline` is frozen.

## Alternatives considered

- **Incremental revisions now**: rejected, many throw-away steps for a schema not yet used.
- **`create_all` without Alembic**: rejected, the deploy runs migrations (`webserver/integration_tests` check the run-once behaviour).
