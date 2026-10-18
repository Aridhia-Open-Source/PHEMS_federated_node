# 0023. Pull requests stored once per repository, fan-out to links, cursors and skipping the gap

- Status: Accepted (built)
- Split out of [0019](0019-global-resources-and-shared-pull-requests.md). Builds on 0021 (global resources and project links) and 0022 (GitProvider and repository identity). Switching off and revoking in general is 0025. The allowed trigger moves are in [0026](0026-state-transition-tables.md).

## Context

Before this change each project stored its own copy of every merged pull request and polled the git provider for it. Two projects on one repository meant two polls, two copies, and a changed-files lookup per project. Which pull requests a project cares about was decided late, in Dagster's evaluate step, with a provider call per unwatched PR.

## Decision

**Store the provider's facts once per global trigger repository.**
- `pull_requests` (`webserver/app/models/pull_request.py`): `trigger_repository_id`, `number`, `title`, `raised_by`, `merged_at`, `merge_commit_sha`, `base_branch`, `files_truncated`. Unique on `(trigger_repository_id, number)` and on `(trigger_repository_id, merge_commit_sha)`.
- `pull_request_files` (`PullRequestFile`): `(pull_request_id, path)` plus `status`. The status is kept because the match rule needs "added". No file content is stored.
- `base_branch` and the changed files are captured at ingest. A PR whose file list the provider cut at its cap has `files_truncated` set.

**The webserver owns the match rule** (`helpers/spec_files.py`, `helpers/pull_request_fanout.py: unmatched_cause`). A link matches a PR when:
- the PR's `base_branch` equals the link's `base_branch`, and
- either `files_truncated` is set, or the PR adds (`status == "added"`) a file ending in `.json` whose directory is the link's `watch_dir` or inside it (whole path segments; an empty `watch_dir` is the whole repository).
The trigger exposes the matched paths as `spec_files`; Dagster's evaluate step (`dagster/app/definitions/sensors/git/pr_parser.py`) reads them and does not re-decide.

**Fan-out.** `POST /global/repositories/triggers/<id>/pull_requests` (`trigger_repositories_api.py: post_pull_requests_batch`) stores a batch and calls `ingest_pull_requests`, which creates a `PullRequestTrigger` for each link where `ProjectTriggerRepository.accepts_triggers` is true (link active and its project enabled) and the PR matches. A non-match gets no trigger and an info-level log naming the cause. There is no `IGNORED` state.
- Idempotent: the PR insert is `ON CONFLICT DO NOTHING` on `uq_pull_requests_repo_number`; stored facts are never changed; triggers are unique on `(project_trigger_repository_id, pull_request_id)`, and a lost race undoes only that trigger (savepoint). Sending a PR again changes nothing. The response lists `created` and `existing` numbers.
- Max 100 PRs per request (400 above). One invalid PR refuses the whole batch. A disabled repository is refused with 400 and stores nothing. Dagster posts in batches of 100 (`ingest_job.py: MAX_BATCH_SIZE`), oldest first.

**Two cursors.**
- The repository's poll cursor is the newest stored `merged_at`, or the repository's creation when nothing is stored (`TriggerRepository.get_ingest_cursor`). It only moves when a PR is stored, so a repository switched off does not advance it.
- Each link has `initial_cursor` plus `initial_cursor_number`, the pair `(merged_at, number)` after which fan-out starts. `PUT .../repositories/triggers/<id>` sets it when the link is created, to the latest stored PR, or to the link's creation time when none is stored. No request sets it directly. `create_triggers` only considers PRs that sort after the pair.
- The link DTO's `pr_cursor` is the newest `merged_at` among the link's own triggers, else `initial_cursor` (`ProjectTriggerRepository.get_pull_request_cursor`).

**`skip_gap`** (`helpers/pull_request_fanout.py`) sets `initial_cursor` to now and `initial_cursor_number` to 0. It runs when:
- a link becomes active: enabled, or un-revoked, by `PUT` or `PATCH` on the link (`project_trigger_repositories_api.py`);
- a trigger repository is switched back on (`trigger_repositories_api.py: patch_repository`);
- a git provider is switched back on (`git_providers_api.py`);
- a project is enabled again (`projects_api.py`).
PRs merged in the gap are still stored once polling resumes, but sort before the cursor and get no trigger.

**No backfill.** Fan-out runs only when a PR is stored. Nothing in the code creates triggers for older PRs; a new link starts after the latest stored PR and a reactivated link starts at now. The "backfill" in older docs (the 2026-10-17 handover, `project/handover/moonshot-plan.md`) was removed (owner decision, 2026-10-18).

**Trigger states and who may create a task.** `UNKNOWN`, `YIELDED`, `REJECTED` (`models/trigger_state.py`). A task is created by `POST /projects/<pid>/repositories/triggers/<repo id>/pull_requests/<n>/task` (`post_task`), which:
- returns the existing task with 200 if there is one;
- otherwise needs the trigger `UNKNOWN`, else 409;
- needs an active link, else 409;
- on a bad spec records `REJECTED` with `state_cause` and returns the error; on a good one marks `YIELDED` and creates the task in one transaction.
Moves are checked by the table in 0026.

## Consequences

- One poll and one stored copy per repository, however many projects watch it. The changed-files lookup happens once, at ingest; evaluate makes no provider call for a PR a project does not watch.
- Projects keep separate evaluation state, so they stay independent.
- Turning something back on is safe: it cannot replay old PRs into running work.
- `pull_request_triggers.pull_request_id` and `project_trigger_repository_id` are `ON DELETE RESTRICT`, so a PR or link with triggers cannot be deleted from under them.
- Ingest is a webserver endpoint called only by Dagster (code TODO: restrict to internal callers).

## Alternatives considered

- **Keep PRs per project.** Isolated, but repeated polls, credentials and copies.
- **Decide the match in Dagster at evaluate time.** Needs a provider call per project per PR, including unwatched ones.
- **An `IGNORED` trigger state for non-matches.** Rejected: it fills the table with rows nobody acts on; a log line is enough.
- **Backfill on enable, un-revoke or an earlier cursor.** Built first, then removed: it replays work the person switched off, and it is the hard part to get exactly-once. `skip_gap` makes all four cases one rule.
- **Changed paths as a JSON column.** A table can be indexed and avoids JSON operators across Postgres and the test database.

## Where it lives

- Schema: PR #555 (branch `split/01-schema`), `webserver/migrations/versions/001_baseline.py` (`pull_requests`, `pull_request_files`, `pull_request_triggers`).
- Behaviour: PR #556 (branch `split/02-webserver`).
- `webserver/app/helpers/pull_request_fanout.py`, `helpers/spec_files.py`
- `webserver/app/models/pull_request.py`, `pull_request_trigger.py`, `project_trigger_repository.py`, `trigger_repository.py`
- `webserver/app/trigger_repositories_api.py`, `project_trigger_repositories_api.py`, `projects_api.py`, `git_providers_api.py`
- `dagster/app/definitions/sensors/git/ingest_job.py`, `pr_parser.py`

## Not built or open

- **Edge: a PR merged just before a switch-off and not yet ingested** is also skipped when the link is turned back on, because the cursor moves to now, not to the time of the switch-off. The exact fix is a `disabled_at` timestamp, with `skip_gap` moving the cursor to that time. Not built.
- An optional backfill is mentioned as "may be added later" in the `skip_gap` docstring; nothing implements it.
- Changing a link's `watch_dir` or `base_branch` applies from the cursor forward; older stored PRs are not re-matched.
- A stored PR with a new number but an already stored `merge_commit_sha` hits the second unique constraint; how that surfaces to the caller was not checked.
- Fan-out takes no row lock; a race is settled by the unique constraint only.
