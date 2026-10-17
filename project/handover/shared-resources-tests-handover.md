# Handover: shared-resources webserver tests, app fixes, owner decisions, e2e script

Branch `moonshot/shared-resources-tests`, PR #553, based on `moonshot/shared-resources-routes`. Written by a cloud Claude session
from the laptop agent's `HANDOVER.md` and `webserver/tests/TEST_PLAN.md`. Delete this file once the work is merged.

## State

- **Webserver tests (condensed, this branch):** 605 passed, 0 failed in about 2m45s (full run of `webserver/tests`; the audit-overflow test, which was the only xfail, was then removed as out of scope). The new files are `test_trigger_repositories_and_links.py`, `test_pull_requests_and_tasks.py`,
  `test_global_resources.py`, `test_projects_api.py`, `test_pagination_and_filters.py`, `test_results_and_delivery.py`,
  `test_healthchecks_all.py`, `test_e2e_flow.py` and `test_live_client_integration.py` (the live-server test runs the real fncli and
  Dagster backend clients against the Flask app). They were condensed from the first, much larger suite by merging overlap and keeping
  one case per rule or failure class; app coverage of the touched modules did not drop by more than 1 point.
- **The full, un-condensed suite** (1370 passed, 1 xfailed: the 83 plan tests plus the in-depth `test_deep_*.py` sweeps) is kept on the
  branch `moonshot/shared-resources-tests-full` (head `ee653cd`) for anyone who wants the exhaustive run.
- **App changes made because the tests found bugs** (two rounds, see "App changes" below): request DTOs reuse the
  `PullRequestRequest.parse` -> `InvalidRequest` pattern, errors are 400/409 instead of 500, lists paginate consistently, and the
  owner decisions below are implemented. Docs (ADR 0019, `docs/architecture`), Dagster, fncli and the e2e script were updated to match.
- **Not run anywhere:** the k8s, Keycloak, Gitea and Dagster end to end (no cluster in the cloud session): use
  `scripts/e2e_shared_resources.sh`. The **Dagster unit tests were edited but not run** (the `dagster` package is not installed in the
  cloud sandbox). The fncli test suite had 61 failures before this work and 57 after (old drift: missing `secret.enabled`, missing
  `trigger_repository` attribute, ...): not fixed, not caused by this work. `dagster/app/tests/test_pr_ingest_sensor.py` still uses
  `active_only=True` (stale before this work).
- **Two stale tests fixed** in `test_dtos.py` (dataset `enabled` field; url is `/global/datasets/<id>`).

## Out of scope on purpose

- **Auth, audit and normal-user permissions.** Decision: auth gets a full rewrite later; for now only the super user and the Dagster
  system user matter, and the rewrite adds granular permissions back. No auth tests, no `@auth`/`@audit` changes. Known gaps, not
  fixed: `PATCH /global/secrets/<label>` has no `can_do_admin` check (POST and DELETE do); a 4096-char `url` on `POST /results` gives a
  500 because the audit row's details column overflows (its test was removed as out of scope).
- Dagster ingest redesign, lock/drain/enabled guard questions and the FastAPI move stay parked, as in the original handover.

## Owner decisions (made in the review session, implemented)

Items marked **(?)** were assumed by the implementer or agreed "for now": the owner should confirm them.

1. **IGNORED state removed.** A PR that does not match a link (wrong base branch, or no `.json` file with status `added` under the
   link's `watch_dir`) creates no trigger for that link; the skip is logged at info level (no recorded reason). `REJECTED` stays and is
   final. Only an `UNKNOWN` trigger can get a task. Migration `001_baseline` edited in place (ADR 0013).
2. **Task through an inactive link: 409** (revoked, disabled by the project, or the global repo disabled). The sensor decides from the
   link list, which now takes `?active=true` (only active links); the 409 is the backstop for a race or a manual call.
3. **A finished task cannot change status** (SUCCESS, FAILED, CANCELED): 409. Setting the same status again is 200. `/retry` is the
   only way back. No other transition rules.
4. **`POST /results` needs a SUCCESS task:** 409 otherwise. Re-posting an existing result is still 200.
5. **(?) `POST /results` through an inactive results link: 409** (revoked, project-disabled, globally disabled repo). Agreed "for now,
   may revisit".
6. **A disabled secret is refused (400)** on create and patch of trigger repos, results repos and datasets
   (`Secret.get_enabled_by_label`). A PATCH that keeps the current secret is not refused.
7. **(?) Dataset `PATCH` returns 200** (was 202), like the other PATCH routes. Assumed for consistency.
8. **(?) `GET /tasks` clamps `page`/`per_page` below 1** (200) like the other lists. Assumed for consistency. Non-numeric is still 400.

## App changes

Round 1 (request validation, from the tests that first failed): strict request models `RepositoryRequest`/`RepositoryPatchRequest`
(`dtos/repository_uri.py`), `DatasetRequest`/`DatasetPatchRequest` (`dtos/dataset.py`), `ProjectRequest` (`dtos/project.py`); wrong
types, bad ports, blank or overlong names and uris give 400 (were 500 or accepted); unknown field on repository POST gives 400;
dataset names lowercased in the DTO; unique violations are 409 (`IntegrityError` handler in `app/__init__.py`); `paginate(error_out=False)`
(page past the end is 200 with empty items), PR lists return pagination values and `pages`; PR `number >= 1`; result PATCH validates
before applying and refuses negative counters and a non-string `step`; `normalise_dir` refuses a non-string; secret PATCH refuses
unknown keys.

Round 2 (the decisions above): `pull_request_fanout.py`, `models/trigger*.py` + migration, `project_trigger_repositories_api.py`
(`post_task`, `?active=true`), `tasks_api.py`, `results_api.py`, `models/secret.py`, the three repository/dataset APIs, plus Dagster
(`pr_evaluate.py` calls the link list with `active=True`, no Python `.active` filter; `IGNORED` removed from `TriggerState` and
`pr_parser.py`, where a PR with no watched file now parses as REJECTED), fncli (`IGNORED` removed; `open-pr --kind unwatched --watch`
can no longer finish because the PR never appears), and the docs/ADR (decisions 10-15 in ADR 0019).

## Review findings outside the tests (read-only review of the whole branch, claims not all run)

- **Dagster ingest can wedge:** one POST of every PR since the cursor, capped at 100 on both sides, no per-repo error handling. A new
  repo with more than 100 merged PRs fails every tick, and one bad token starves ingest for all repos.
- **Ingest vs link create race:** a PR can end up without a trigger for a link created at the same moment (`pull_request_fanout.py`).
- **Revoked/disabled secrets are not enforced at use:** Dagster reads the token from the K8s secret without checking
  `ProjectSecret.active` or `Secret.enabled` (decision 6 only stops new references).
- **Cursor on link create** uses the latest stored PR's `merged_at`, not the creation time, when the repo has stored PRs, so a gap can
  replay history (contradicts ADR 0019 section 3).
- **K8s RBAC too broad:** the key-rotation ClusterRole can touch all Secrets cluster-wide; the Dagster roles can read every secret in
  the release namespace. The Dagster password rotation patches the secret but nothing restarts the code server (uncertain).
- **fncli:** `get_or_assign_*` returns an existing link even if it points at a different repo or settings.
- **`POST /tasks/<id>/retry` on a SUCCESS task returns 400** (works only on a failed task): not confirmed whether intended.
- **Docs drift:** `webserver/app/static/openapi.json` still documents `/global/datasets/by-name`, `/task_requests*`,
  `/whitelisted_images*`; the "# Claude (issue 1)" comments are still in `pr_ingest.py`, `backend.py` and `trigger_repositories_api.py`.
- **Dagster still filters in Python:** `launcher.py:24` and `pr_evaluate.py:27` (projects by enabled and locked), `launcher.py:46` and
  `delivery/results.py:66` (links by `.active`), `delivery/results.py:187` (scan of all PRs for a task id), `pull_request_sync.py`
  (results by step), fncli `find_*`. `GET /projects?enabled=true` is untested; `parse_query_params` has no boolean coercion (uncertain).

## Open questions for the owner

- Confirm the three **(?)** decisions (5, 7, 8).
- Forward-only PR states (a YIELDED trigger can still be PATCHed back to UNKNOWN: not changed).
- Should the first PUT of a results link need the project locked (the other link kinds do not)?
- RBAC narrowing and the rotation restart; batch size and retry strategy for Dagster ingest.

## Running the tests

Normal route (laptop): `cd webserver && ./run_tests.sh` (Docker Compose, builds `build/test.Dockerfile`).

Quicker, one file, from a venv against any Postgres (CI uses 17; the cloud session ended up on a local Postgres 16, which also works):
```
docker run -d --name fn-test-db -e POSTGRES_DB=test_app -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=test_app -p 127.0.0.1:55432:5432 postgres:17-alpine
cd webserver && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
# export the env vars from run_tests.sh, with PGHOST=127.0.0.1 PGPORT=55432
.venv/bin/pytest tests/test_deep_projects_api.py -q -p no:cacheprovider --no-cov -W ignore
```
- Each test creates and drops all tables in the database named by `BACKEND_DB_NAME`, so two pytest processes need **different
  databases** (create `test_app_1`, `test_app_2`, ... and set `PGDATABASE` and `BACKEND_DB_NAME` per process).
- `test_live_client_integration.py` skips itself when `scripts/fncli` is not importable (the CI test container mounts only
  `webserver/tests` and `webserver/app`), so CI runs everything else.
- Parallel agents: give each its own git worktree **created by hand from the branch tip** (`git worktree add -b <name> <path> HEAD`);
  the agent tool's own worktree isolation cut some worktrees from an old commit, so they lacked the new code. Override `PYTHONPATH` to
  the worktree's `webserver/` after sourcing any env file.

Cloud-session notes (only matter if you use a Claude cloud environment): `dockerd` was installed but not running and died during the
session (start it by hand); Docker Hub rate-limits anonymous pulls (429), so pull from `mirror.gcr.io` and retag; containers have no DNS,
only the proxy, which refuses plain-HTTP (use `apt` over HTTPS in builds). The compose build was never completed there, so the tests ran
from a venv. A local kind cluster does not start in that sandbox (runc sandbox creation fails), so there is no real k8s there.

## E2E on the laptop

`scripts/e2e_shared_resources.sh` (with `scripts/e2e_check.py`). It checks the preconditions, then: `fncli setup-project`, `fncli
start-sensor --sensor all`, opens and merges a watched, an unwatched and an invalid PR, waits for YIELDED (with a task) and REJECTED
and checks the unwatched PR created **no trigger** (each link has exactly 2 PRs), then waits for the task to reach SUCCESS, prints a
snapshot and tears down. `KEEP=1` leaves the project; `SKIP_TASKS=1` stops after the PRs are evaluated. It needs the dev cluster from
`scripts/fncli/EXAMPLES.md` ("Run the project from scratch"). It has **never been run**: expect small fixes on the first go. If a step
fails it prints `fncli sensor-status`.

## Suggested next steps

1. Run the e2e script and the full webserver suite locally; run the Dagster unit tests where `dagster` is installed.
2. Confirm or change the **(?)** decisions.
3. Fix the review findings you care about (ingest batch/retry, the ingest-vs-link race, secret enforcement at use, RBAC).
4. Review the Gitea moonshot work (not started; see `project/handover/gitea-mirror-plan.md`).
