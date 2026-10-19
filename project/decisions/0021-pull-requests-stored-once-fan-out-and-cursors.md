# 0021. Pull requests stored once per repository, fanned out to project links, with cursors

- Status: Accepted (built). 2026-10-19.
- Detail for section 3 of [0019](0019-global-resources-and-shared-pull-requests.md). Related: [0022](0022-state-transition-tables.md) (trigger states), [0023](0023-dagster-pipeline-ops-sensors-and-retries.md) (who calls the ingest).

## Context

Before the shared model, each project polled the git provider for its own copy of a repository and stored its own pull requests. With one global trigger repository and several project links ([0019](0019-global-resources-and-shared-pull-requests.md)), the provider must be polled once and each link must get only the pull requests it watches, without replaying history when a link is created or switched back on.

## Decision

**One copy of the facts.** `pull_requests` holds what the provider says, once per global trigger repository, unique on `(trigger_repository_id, number)`. `pull_request_files` holds the changed paths and their status. `files_truncated` marks a pull request whose file list hit the provider's cap. `pull_request_triggers` is the per-project part: one trigger per `(project link, pull request)`, with the evaluation state ([0022](0022-state-transition-tables.md)).

**Ingest.** `POST /global/repositories/triggers/<id>/pull_requests` takes up to 100 pull requests (more is a 400) and is refused with a 400 for a repository that is not active (disabled, revoked, or on such a provider). `store_pull_request` inserts with `ON CONFLICT DO NOTHING` on the unique constraint, so an existing number is left as it was and two concurrent posts store it once. The answer lists the numbers `created` and `existing`; posting the same pull requests again changes nothing.

**Fan-out** (`webserver/app/helpers/pull_request_fanout.py`). For the pull requests newly stored by a call, `fan_out` runs `create_triggers` for every link that `accepts_triggers`: the link is active (global repository and provider on, link enabled, not revoked) and its project is enabled and not revoked. A link gets a trigger when the pull request's `base_branch` equals the link's, and either `files_truncated` is set or `spec_files` finds a file the pull request adds, ending in `.json`, under the link's `watch_dir`. Otherwise it gets no trigger and the cause is logged at info level. The match uses stored data only, with no provider call. There is no `IGNORED` state.

**Two cursors.**
- The global poll cursor is the latest `merged_at` stored for the repository, or the repository's creation when none is stored (`TriggerRepository.get_ingest_cursor`, shown as `pr_cursor`). It only moves forward as pull requests are stored.
- A link's cursor is the pair `initial_cursor` and `initial_cursor_number`. `create_triggers` only considers pull requests after it, ordered by `(merged_at, number)`, so two merges in the same second are told apart. It is set when the link is created, from the latest stored pull request (`merged_at` and `number`), or the link's creation time with number 0 when none is stored. No request sets it directly.

**`skip_gap`.** When a link becomes active again, its cursor moves to now with number 0, so what was merged in the gap is still stored by the poll but gets no trigger. This runs when: a link is enabled or un-revoked (PUT or PATCH on the link), its global trigger repository is enabled or un-revoked, its git provider is enabled or un-revoked, or its project is enabled or un-revoked.

**Optional backfill, only at project enable.** `PATCH /projects/<id> {"enabled": true, "backfill": true}` leaves the cursors alone and calls `create_triggers` for every link that now accepts triggers, creating the triggers of the pull requests stored while the project was off. `backfill` is a 400 unless the body also has `enabled: true` and the project is currently disabled, and it is not stored. Repeating it is safe: a pair `(link, pull request)` already has its trigger. Pull requests before the cursor stay without a trigger. There is no backfill for the other switches.

**Config changes.** Changing a link's `watch_dir` or `base_branch` does not replay older pull requests; matching applies to pull requests stored afterwards (or created by a later backfill).

## Consequences

- One provider poll and one stored copy per repository, however many projects watch it.
- A project that is off still has pull requests stored; the choice at enable is skip (default) or backfill.
- A link switched back on never sees history it did not watch. A link that missed pull requests can only get them through a project backfill.
- The match rule lives in the webserver; Dagster trusts the `spec_files` the trigger exposes ([0023](0023-dagster-pipeline-ops-sensors-and-retries.md)).
- A truncated pull request matches every link of the right branch, so it can create triggers that the evaluate step then rejects for having no spec file.

## Alternatives considered

- **Pull requests per link only:** no sharing of provider facts; the duplication stays.
- **Replay history on enable:** surprising for a link that never watched it; the optional project backfill covers the case that matters.
- **An `IGNORED` trigger state for non-matching pull requests:** rejected, no row is cheaper and the cause is logged.
- **A JSON array of paths on the pull request:** a table can be filtered in SQL and needs no JSON operators.

## Where it lives

- `webserver/app/helpers/pull_request_fanout.py`, `helpers/spec_files.py`
- `webserver/app/models/pull_request.py`, `pull_request_trigger.py`, `project_trigger_repository.py`
- `webserver/app/trigger_repositories_api.py`, `project_trigger_repositories_api.py`, `projects_api.py`, `git_providers_api.py`

## Not built or open

- Backfill for a link, a repository or a provider being switched back on.
- `pull_requests` is also unique on `(trigger_repository_id, merge_commit_sha)`, but `store_pull_request` only absorbs a conflict on the number. A repeated merge sha under a new number would hit the other constraint; how that surfaces to the caller was not checked.
