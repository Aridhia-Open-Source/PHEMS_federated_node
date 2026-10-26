# 0011. Pull requests stored once per repository, fanned out to project resources, with cursors

## Context

With one global trigger repository and several project resources ([0006](0006-global-resources-and-project-resources.md)), the provider must be polled once and each project resource must get only the pull requests it watches, without replaying history when a project resource is created or switched back on.

## Decision

**One copy of the facts.** `pull_requests` holds what the provider says, once per global trigger repository: `number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`, `base_branch`, `files_truncated`. It is unique on `(trigger_repository_id, number)` and on `(trigger_repository_id, base_branch, merge_commit_sha)`: a fast-forward or rebase merge can give two base branches the same commit, so both pull requests are stored, but one commit on one base branch belongs to one pull request. `store_pull_request` ignores a conflict on either rule and returns the existing row, found by number, else by `(repository, base_branch, sha)`; a pull request that clashes only on the commit is skipped with a warning naming both numbers, gets no triggers, and does not fail the batch. `pull_request_files` holds the changed paths and their status, captured once at ingest, as a table so that paths can be filtered in SQL against `watch_dir`. `files_truncated` marks a pull request whose file list hit the provider's cap (GitHub caps it at 3000); ingest pages through all of it, and a truncated pull request is treated as matching every path. `pull_request_triggers` ([0001](0001-polymorphic-triggers.md)) is the per-project part: one trigger per `(project resource, pull request)`, carrying the evaluation state; `title`, `raised_by` and the other facts are read through the pull request. A project resource cannot be removed for real while triggers exist (`RESTRICT`).

**Ingest.** `POST /global/repositories/triggers/<id>/pull_requests` takes up to 100 pull requests (more is a 400) and is refused with a 400 for a repository that is not active (disabled, revoked, or on such a provider). `store_pull_request` inserts with `ON CONFLICT DO NOTHING` on the unique constraint, so an existing number is left as it was and two concurrent posts store it once. The answer lists the numbers `created` and `existing`; posting the same pull requests again changes nothing.

**Fan-out** (`webserver/app/helpers/pull_request_fanout.py`). For the pull requests newly stored by a call, `fan_out` runs `create_triggers` for every project resource that `accepts_triggers`: the project resource is active (global repository and provider on, project resource enabled, not revoked) and its project is enabled and not revoked. A project resource gets a trigger when the pull request's `base_branch` equals the project resource's, and either `files_truncated` is set or `spec_files` finds a file the pull request adds, ending in `.json`, under the project resource's `watch_dir`. Otherwise it gets no trigger and the cause is logged at info level. The match uses stored data only, with no provider call, so evaluate never calls the provider for a pull request a project does not watch. A new trigger starts `UNKNOWN`.

**Two cursors.**
- The global poll cursor is the latest `merged_at` stored for the repository, or the repository's creation when none is stored (`TriggerRepository.get_ingest_cursor`, shown as `pr_cursor`). It only moves forward as pull requests are stored, and does not move while a repository is off, so what was merged meanwhile is ingested once it is back on.
- A project resource's cursor is the pair `initial_cursor` and `initial_cursor_number`. `create_triggers` only considers pull requests after it, ordered by `(merged_at, number)`, so two merges in the same second are told apart. It is set when the project resource is created, from the latest stored pull request, or the project resource's creation time with number 0 when none is stored. No request sets it directly. The project resource's DTO shows the cursor it has reached (`pr_cursor`).

**`skip_gap`.** When a project resource becomes active again, its cursor moves to now with number 0, so what was merged in the gap is still stored by the poll but gets no trigger. This runs when a project resource is enabled or un-revoked (PUT or PATCH on the project resource), or its global trigger repository, its git provider or its project is enabled or un-revoked.

**Optional backfill, only at project enable.** `PATCH /projects/<id> {"enabled": true, "backfill": true}` leaves the cursors alone and calls `create_triggers` for every project resource that now accepts triggers, creating the triggers of the pull requests stored while the project was off. `backfill` is a 400 unless the body also has `enabled: true` and the project is currently disabled, and it is not stored. Repeating it is safe: a pair `(project resource, pull request)` already has its trigger. Pull requests before a project resource's cursor stay without a trigger. There is no backfill for the other switches.

**Config changes.** Changing a project resource's `watch_dir` or `base_branch` does not replay older pull requests; matching applies to pull requests stored afterwards (or created by a later backfill).

## Consequences

- One provider poll and one stored copy per repository, however many projects watch it.
- A project that is off still has pull requests stored; the choice at enable is skip (default) or backfill.
- A project resource switched back on never sees history it did not watch. A project resource that missed pull requests can only get them through a project backfill.
- The match rule lives in the webserver; Dagster trusts the `spec_files` the trigger exposes ([0014](0014-dagster-pipeline-ops-sensors-and-retries.md)).
- A truncated pull request matches every project resource of the right branch, so it can create triggers that the evaluate step then rejects for having no spec file.

## Alternatives considered

- **Pull requests per project resource only:** no sharing of provider facts; the duplication stays.
- **Replay history on enable:** surprising for a project resource that never watched it; the optional project backfill covers the case that matters.
- **An ignored trigger state for non-matching pull requests:** no row is cheaper and the cause is logged.
- **A JSON array of paths on the pull request:** a table can be filtered in SQL and needs no JSON operators.
- **One mirror (a Gitea organisation) per project:** repeats the polling and the copy per project; global repositories stored once make it unnecessary.

## Where it lives

- `webserver/app/helpers/pull_request_fanout.py`, `helpers/spec_files.py`
- `webserver/app/models/pull_request.py`, `pull_request_trigger.py`, `project_trigger_repository.py`
- `webserver/app/trigger_repositories_api.py`, `project_trigger_repositories_api.py`, `projects_api.py`, `git_providers_api.py`

## Open questions

- Backfill for a project resource, a repository or a provider being switched back on.
- A pull request merged just before a project resource is switched off, and not yet ingested, is also skipped when the project resource is switched on (`skip_gap` moves the cursor to now).
