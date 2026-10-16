# Handover: shared-resources webserver tests, app bugs found, e2e script

Branch `moonshot/shared-resources-tests`, PR #553, based on `moonshot/shared-resources-routes`. Written by a cloud Claude session
from the laptop agent's `HANDOVER.md` and `webserver/tests/TEST_PLAN.md`. Delete this file once the work is merged.

## State

- **Tests:** last complete full run (with the app fixes in): 1287 passed, 14 xfailed, 61 xpassed, 0 failed (8 min). The 61 xpassed
  tests then had their xfail markers removed; the five affected files were re-run on their own with 0 failed and 0 xpass, but the
  whole suite was not re-run afterwards, so expect 1348 passed and 14 xfailed and **run the full suite once to confirm**. The 83 basic tests from `TEST_PLAN.md` are
  in 9 files. A second wave of in-depth files is `test_deep_*.py`, plus `test_live_client_integration.py`.
- **App code changed after the tests found bugs** (commit "Validate request bodies and fix error statuses found by the new tests",
  17 files, +229 -117): request DTOs reuse the `PullRequestRequest.parse` -> `InvalidRequest` pattern, see "App bugs" below. The
  tests first went in with the correct expectation marked `xfail(strict=False)`; 61 of the 75 now pass and lost their marker.
  The 14 left are the decisions below.
- **Two stale tests fixed** in `test_dtos.py` (dataset `enabled` field; url is `/global/datasets/<id>`).
- **Not run anywhere:** the k8s, Keycloak and Gitea end to end (no cluster in the cloud session). Use `scripts/e2e_shared_resources.sh`.

## Out of scope on purpose

- **Auth, audit and normal-user permissions.** Decision: auth gets a full rewrite later; for now only the super user and the Dagster
  system user matter, and the rewrite adds granular permissions back. No auth tests, no `@auth`/`@audit` changes. Known gap, not fixed:
  `PATCH /global/secrets/<label>` has no `can_do_admin` check (POST and DELETE do). A 4096-char `url` on `POST /results` gives a 500
  because the audit row's details column overflows.
- Dagster ingest redesign, lock/drain/enabled guard questions and the FastAPI move stay parked, as in the original handover.

## Running the tests

Normal route (laptop): `cd webserver && ./run_tests.sh` (Docker Compose, builds `build/test.Dockerfile`).

Quicker, one file, from a venv against any Postgres 17 (this is what the cloud session did):
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
- The full suite takes about 8 minutes in one process.

Cloud-session notes (only matter if you use a Claude cloud environment): `dockerd` was installed but not running (start it by hand);
Docker Hub rate-limits anonymous pulls (429), so pull `python:3.13.5-slim` from `mirror.gcr.io` and retag; build steps need the proxy
and `apt` over HTTPS (the proxy refuses plain HTTP). The compose build was never completed there, so the tests ran from a venv.

## App bugs found by the tests

**Fixed** (tests now plain passes):
1. Create/PATCH bodies had no type or length validation: new strict models `RepositoryRequest`/`RepositoryPatchRequest`
   (`dtos/repository_uri.py`), `DatasetRequest`/`DatasetPatchRequest` (`dtos/dataset.py`), `ProjectRequest` (`dtos/project.py`);
   wrong types, bad ports, blank or 300-char names and 5000-char uris now give 400 (were 500 or accepted); unknown field on repository
   POST gives 400. Dataset names are lowercased in the DTO, so POST and PATCH agree.
2. Unique violations are 409 (`IntegrityError` handler in `app/__init__.py`), and dataset POST/PATCH pre-check the lowercased name.
3. `PATCH /global/datasets/<id>`: empty or non-object body gives 400, `type` is checked, `name` lowercased. **Still returns 202**
   (the other PATCH routes return 200; left as an owner decision).
4. Pagination: `paginate(error_out=False)`, so a page past the end is 200 with empty items and `page`/`per_page` below 1 clamp. The
   project and global PR lists return pagination values and `pages`. **Inconsistency left in:** `GET /tasks` returns 400 for `page` or
   `per_page` below 1 (a pre-existing test expects it), the other lists clamp.
5. PR ingest `number` must be >= 1. Result PATCH validates everything before applying, refuses negative `number`/`attempts` and a
   non-string `step`. `normalise_dir` refuses a non-string directory (results link `target_dir`). Secret PATCH refuses unknown keys.

**Still open, needs an owner decision** (14 `xfail` tests, reasons in the markers):
- `POST .../pull_requests/<n>/task` creates a task for an IGNORED/REJECTED PR, and on a revoked or project-disabled link. (A REJECTED
  PR taking a corrected spec looks intended: that case may be the test being wrong.)
- A task in SUCCESS/FAILED/CANCELED can be PATCHed back to RUNNING (no forward-only rule; `/retry` exists).
- `POST /results` is accepted for a FAILED/CANCELED task, a revoked link, a project-disabled link and a globally disabled repo.
- A repository or dataset can reference a disabled secret.
- `POST /results` with a 4096-char `url` gives 500 (audit row overflow; audit is out of scope).

Confirmed from the original handover's list: ingest creates triggers for disabled projects while `?active_link=true` omits them;
duplicate dataset name 500; dataset PATCH 202; trigger-link delete with PRs gives a raw FK 400; secret PATCH not admin-only (out of
scope); secret PATCH `updated_at` uses local time (`secrets_api.py:208`).

## Review findings outside the tests (read-only review of the whole branch, claims not all run)

- **Dagster ingest can wedge:** one POST of every PR since the cursor, capped at 100 on both sides, no per-repo error handling. A new
  repo with more than 100 merged PRs fails every tick, and one bad token starves ingest for all repos.
- **Ingest vs link create race:** a PR can end up without a trigger for a link created at the same moment (`pull_request_fanout.py`).
- **Revoked/disabled secrets are not enforced:** Dagster reads the token from the K8s secret without checking `ProjectSecret.active`
  or `Secret.enabled`.
- **Cursor on link create** uses the latest stored PR's `merged_at`, not the creation time, when the repo has stored PRs, so a gap can
  replay history (contradicts ADR 0019 section 3).
- **K8s RBAC too broad:** the key-rotation ClusterRole can touch all Secrets cluster-wide; the Dagster roles can read every secret in
  the release namespace. The Dagster password rotation patches the secret but nothing restarts the code server (uncertain).
- **fncli:** `get_or_assign_*` returns an existing link even if it points at a different repo or settings.
- **Docs drift:** `webserver/app/static/openapi.json` still documents `/global/datasets/by-name`, `/task_requests*`,
  `/whitelisted_images*`; the "# Claude (issue 1)" comments are still in `pr_ingest.py`, `backend.py` and
  `trigger_repositories_api.py`.
- **Dagster still filters in Python** what the webserver should filter: `launcher.py:24` and `pr_evaluate.py:27` (projects by enabled
  and locked), `launcher.py:46`, `pr_evaluate.py:31` and `delivery/results.py:66` (links by `.active`), `delivery/results.py:187` (scan
  of all PRs for a task id), `pull_request_sync.py` (results by step), fncli `find_*`. `?active_link=true` and `?state=` exist.
  `GET /projects?enabled=true` is untested; `parse_query_params` has no boolean coercion (uncertain).

## Decisions for you

- Forward-only task and PR states (what blocks a task going back to RUNNING, a YIELDED PR going back to UNKNOWN).
- Should `post_task` and `POST /results` refuse on a revoked/disabled link, a locked project or a terminal task?
- Should the first PUT of a results link need the project locked (the other link kinds do not)?
- RBAC narrowing and the rotation restart.
- Batch size and retry strategy for Dagster ingest.

## E2E on the laptop

`scripts/e2e_shared_resources.sh` (with `scripts/e2e_check.py`). It checks the preconditions, then: `fncli setup-project`, `fncli
start-sensor --sensor all`, opens and merges a watched, an unwatched and an invalid PR, waits for YIELDED (with a task), IGNORED and
REJECTED, then waits for the task to reach SUCCESS, prints a snapshot and tears down. `KEEP=1` leaves the project; `SKIP_TASKS=1` stops
after the PRs are evaluated. It needs the dev cluster from `scripts/fncli/EXAMPLES.md` ("Run the project from scratch"). It has
**never been run**: expect small fixes on the first go. If a step fails it prints `fncli sensor-status`.

## Cloud integration

Not possible in the cloud sandbox: a local kind cluster does not start there, so there is no real k8s, Keycloak, Gitea or Dagster run.
Use `scripts/e2e_shared_resources.sh` on the laptop. In the sandbox, `docker` and `docker compose` work (start `dockerd` by hand);
pull Docker Hub images from `mirror.gcr.io` (anonymous Hub pulls are rate-limited); containers have no DNS, only the proxy.
Real client-to-server coverage in the sandbox: `test_live_client_integration.py`.

## Suggested next steps

1. Run the e2e script and the full suite locally.
2. Decide the state rules under "Still open" and flip the 14 xfails; the other dataset PATCH detail (202 vs 200) and the `/tasks`
   400-vs-clamp inconsistency.
3. Add the Dagster-side tests (the Dagster and fncli unit tests still use the old routes) and the missing query options.
4. Review the Gitea moonshot work (not started).
