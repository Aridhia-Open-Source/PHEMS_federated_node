# 0025. Switching off, revoking and soft delete

- Status: Accepted (built), with the differences listed under "Not built or open"
- Part of the split of [0019](0019-global-resources-and-shared-pull-requests.md). Related: [0021](0021-global-resources-and-project-links.md), [0023](0023-pull-requests-stored-once-fan-out-and-cursors.md) (cursors, skipping the gap), [0024](0024-task-configuration-pinning.md) (pinning replaces the drain), [0026](0026-state-transition-tables.md).

## Context

- A resource can be turned off for a while, withdrawn for good, or removed. Before this, each of those needed the project locked and drained, and delete was a hard delete that failed on foreign keys or orphaned rows.
- Pinning ([0024](0024-task-configuration-pinning.md)) makes edits safe without a drain, so the remaining question is what each switch does to work already in the system.

## Decision

### Meanings

- **`enabled` (switched off):** stops new work. Work in flight finishes, and things resume when it is back on. Set by the project on a link, or globally on a resource, a provider or a project (`PATCH`).
- **`revoked`:** admin only (`g.caller_is_admin`, 401 otherwise), immediate, for good. It does not touch `enabled`, so un-revoking restores the earlier state. A revoked trigger link gets no trigger and its triggers get no task; a revoked results link makes a result `REVOKED`, final.
- **Active** (`active` property on each link model): the global resource is enabled (a repository's provider too), the link is `enabled`, and it is not `revoked`. `ProjectTriggerRepository.accepts_triggers` also needs the project enabled.
- **`locked` (project):** a pause that keeps the backlog. It is not a correctness rule. Only the evaluate sensor (`pr_evaluate.py`: `get_projects(enabled=True, locked=False)`) and `POST /projects/<pid>/tasks` (409) honour it. Creating a project's results link still needs it (`helpers/project_lock.py`, `require_locked`).

### What each switch does

| State | New pull requests | A task not launched yet | A finished task's results |
|---|---|---|---|
| Trigger link off | Stored, no trigger; link's cursor moves to now when on again (`skip_gap`) | Launches | Delivered |
| Trigger repository or its provider off | Not polled (`?pollable=true`) and the batch `POST` is a 400: not stored. Stored by catch-up when back on, but no trigger (`skip_gap`) | Launches | Delivered |
| Project off | Stored, no trigger (`accepts_triggers`); `skip_gap` when on again | Waits: the launcher only reads `enabled=True` projects | Delivered (retry sensor reads all projects) |
| Results link, results repository or its provider off | n/a | Launches | Result created `FAILED` at step `UNKNOWN`, "results link switched off"; the retry sensor delivers it once the link is active |
| Dataset link or global dataset off | n/a | `FAILED` at launch, naming the dataset (`launcher._launch`, `ProjectDataset.active`) | n/a |
| Dataset's secret off | n/a | `FAILED` at launch | n/a |
| **Revoked** trigger link | No trigger | Its existing triggers cannot create a task: 409 (`project_trigger_repositories_api`, the `/task` route) | n/a |
| **Revoked** dataset link | n/a | `FAILED` at launch | n/a |
| **Revoked** results link | n/a | Launches | Result `REVOKED`, `FAILED`, final, never delivered |
| **Deleted** link | Same as revoked (`soft_delete` sets `revoked`) | Trigger link as revoked. Dataset link: see "Not built or open" | Results link: `REVOKED`, final |

- A switched-off result is not final. `ResultsDeliveryRetrySensor` (`dagster/app/definitions/sensors/task/delivery.py`) lists `FAILED` results with `active_link=true` (`results_api.get_results`), skips final steps (`FINAL`: `OPENED`, `MERGED`, `CLOSED`, `REVOKED`, `STALE`) and results at `DAGSTER_DELIVERY_MAX_ATTEMPTS`. A revoked link is not active, so it is never retried. Artifacts must therefore outlive the task's end until delivery.
- `POST /results` order: existing result, task `SUCCESS` (else 409), revoked (`REVOKED`), stale (`STALE`, [0024](0024-task-configuration-pinning.md)), switched off (`FAILED`). It reads the link with `include_deleted`, so a deleted link counts as revoked.
- A 404 or 409 from delivery (project, task or repository gone; task not `SUCCESS`) is logged and not retried (`ResultsDelivery._stop_if_refused`).
- Secrets are outside the table: credentials are not in the pinned configuration, so a rotation reaches running work. A disabled secret blocks creating a repository or dataset on it (400).

### Soft delete

- `SoftDeleteMixin` (`webserver/app/helpers/soft_delete.py`) adds `deleted_at` and `soft_delete()`, which also sets `revoked` on links. It is on projects, the four link tables, secrets, datasets, trigger and results repositories, and git providers.
- One `do_orm_execute` listener (`hide_deleted`) adds `deleted_at IS NULL` to every ORM select and collection load, unless the query has `execution_options(include_deleted=True)`. Many-to-one references (`task.project`, `result.assignment`) still load a deleted row. The API treats a deleted row as gone (404, not listed). The only `include_deleted` caller is `results_api.post_result`.
- Names are reusable: partial unique indexes `WHERE deleted_at IS NULL` (`_unique_when_live` in `001_baseline.py`) cover project name, secret label and key, dataset name, provider name and uri, link pairs and repository `(provider, repo_path)`.
- Deleting a link revokes it. Deleting a project soft deletes it and all its links (`projects_api.delete_project`); tasks and triggers stay.
- A global dataset or repository with live links is a 409 listing the projects, unless `?force=true`, which soft deletes every link too (`delete_global`). A secret in use by a repository or dataset is a 409 (no force); otherwise it goes with its links and its stored value is deleted. A provider with repositories is a 409.

### Bulk revoke

- `POST /global/<kind>/<id>/revoke` (datasets, `repositories/triggers`, `repositories/results`, secrets by label) sets `revoked` on every project's link (`helpers/revoke.py`, `revoke_links`). Admin only, no lock, idempotent, returns the link ids. Un-revoking is per link (`PATCH ... {"revoked": false}`).

### Drain checks are gone

- No edit, flip or delete calls a drain guard. Soft delete leaves history readable and pinning stops a task running against a changed setup, so there is nothing to wait for.
- Race: none for edits. A task created in the gap carries the old snapshot and fails at launch or is `STALE`, or gets a `REVOKED` result. What remains is creating the results link: `require_locked` is checked, but `POST .../task` does not check the lock, so a task can be created between the check and the link. Worst case it fails or is not delivered; no other project is affected. A running delivery is not stopped by a revoke; its result may still be delivered once.
- Emergency routine: revoke first (`POST /global/.../revoke`), which is immediate, then edit or delete at leisure.

## Consequences

- Switching off costs nothing and loses nothing except the gap on trigger links, which is skipped on purpose ([0023](0023-pull-requests-stored-once-fan-out-and-cursors.md)).
- Revoke is the one instant, irreversible-in-effect action: results for a revoked link are never delivered, even if it is un-revoked later.
- Every ORM query now carries a filter; code that needs a deleted row must say so.
- Deleted rows stay in the database for audit, with no purge and no API to read them.

## Alternatives considered

- **Keep drain-and-lock guards on every edit and flip:** about 25 calls in 8 files, and a hard stop for the controller while anything runs.
- **Hard delete with cascade:** loses history, and orphaned triggers and tasks (`tasks.trigger_id` is RESTRICT).
- **A per-query `.filter(deleted_at.is_(None))`:** easy to forget; one listener cannot be.
- **A `disabled_reason` string instead of `revoked`:** there is one reason.
- **Hold a result while the link is off (a `HELD` step) or a sweep sensor:** not built; the `FAILED` result plus the retry sensor does the job.

## Where it lives

- PR #555 (schema and mixin): `webserver/app/helpers/soft_delete.py`, `models/*`, `migrations/versions/001_baseline.py`.
- PR #556 (webserver, `split/02-webserver`): `projects_api.py`, `datasets_api.py`, `secrets_api.py`, `trigger_repositories_api.py`, `results_repositories_api.py`, `git_providers_api.py`, `project_trigger_repositories_api.py`, `results_api.py`, `helpers/revoke.py`, `helpers/pull_request_fanout.py` (`skip_gap`).
- PR #557 (Dagster, `split/03-dagster`): `dagster/app/definitions/sensors/task/launcher.py`, `.../task/delivery.py`, `dagster/app/delivery/results.py`.

## Not built or open

- **A deleted dataset link leaves its task PENDING.** The launcher's `get_project_dataset` gets a 404 for a deleted link (the route hides deleted rows), the sensor logs it and retries every tick. Only a revoked, switched-off link gives `FAILED` naming the dataset. 0019's table says `FAILED` for deleted too; the code does not.
- 0019 says locked pauses "evaluation and launch". The launcher does not read `locked`; a locked, enabled project still launches PENDING tasks.
- `POST .../pull_requests/<n>/task` does not check the project lock.
- The comment on `locked` in `webserver/app/models/project.py` still mentions drain.
- No backfill of the gap; no purge of deleted rows; no way to kill a task or delivery already running.
