# Handover: shared-resources webserver tests, app bugs found, e2e script

Branch `moonshot/shared-resources-tests`, PR #553, based on `moonshot/shared-resources-routes`. Written by a cloud Claude session
from the laptop agent's `HANDOVER.md` and `webserver/tests/TEST_PLAN.md`. Delete this file once the work is merged.

## State

- **Tests:** `webserver/tests` has 1287 passing and 75 xfailed, 0 failed (full run, 8 min). The 83 basic tests from `TEST_PLAN.md` are
  in 9 files. A second wave of in-depth files is `test_deep_*.py`, plus `test_live_client_integration.py`.
- **No app code was changed.** Every test that exposes an app bug keeps the correct expectation and is `xfail(strict=False)` with the
  request, actual and expected result in the reason. Fixing a bug turns its xfail into an xpass: delete the marker then.
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

## App bugs found (the xfails), by root cause

Detail for each is in the xfail reason; grep `xfail` in `webserver/tests`.

1. **No input validation on create/PATCH bodies** (dataset, trigger and results repositories). Wrong types and bad values give 500 or
   are accepted: `name=5`, `name=["x"]`, `name=""`, 300-char name, `host=""`/`5`, `port` as string/float/bool/-1/70000, `type=5`,
   `secret_label=5`, `api_uri=5`, 5000-char uri, unknown field accepted on repository POST. Expected 400. Project create has the same
   shape: blank name 201, 300-char name 500, `name=123` 500.
2. **Duplicate dataset name gives 500, expected 409** (POST, and PATCH renaming onto an existing name). The other global resources
   return 409.
3. **`PATCH /global/datasets/<id>`:** returns 202 (others 200); `type="nosql"` accepted; name not lowercased (POST lowercases, and
   `Project.resolve_dataset` compares lowercase, so a mixed-case name can never be resolved); empty body gives 500.
4. **FK failures on delete return a generic 400, expected 409 with a reason:** trigger link with PRs, dataset a task ran on, results
   link with results, global repositories.
5. **Pagination:** past-the-end page and `page`/`per_page` of 0 or negative give 404 on `/projects`, `/global/datasets`, `/tasks`
   (`paginate()` with `error_out=True`); the project PR list returns 200 and echoes `page: 0`; the global PR list has no `pages` field.
   List shapes are inconsistent (`items` vs `tasks` vs plain arrays): asserted as is.
6. **PR ingest:** PR `number` 0 or -1 is stored (no lower bound on `PullRequestRequest.number`).
7. **State rules not enforced:**
   - `POST .../pull_requests/<n>/task` creates a task for an IGNORED/REJECTED PR, and on a revoked or project-disabled link.
   - A task in SUCCESS/FAILED/CANCELED can be PATCHed back to RUNNING.
   - `POST /results` is accepted for a FAILED/CANCELED task, a revoked link, a project-disabled link and a globally disabled repo.
   - Results PATCH with an invalid `state` returns 400 but still saves the `step`.
8. **Results:** non-string `target_dir` accepted; unhashable `step` gives 500; negative `number`/`attempts` accepted.

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

## Suggested next steps

1. Run the e2e script and the full suite locally.
2. Fix app bugs 1 to 6 and 8 (mechanical: reuse the DTO and `InvalidRequest` patterns, `page_of`/`parse_query_params`); decide the
   state rules in section 7.
3. Add the Dagster-side tests (the Dagster and fncli unit tests still use the old routes) and the missing query options.
4. Review the Gitea moonshot work (not started).
