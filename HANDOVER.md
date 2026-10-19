# Handover: shared-resources webserver tests

Branch: `moonshot/shared-resources-routes`. Pull it before you start. Delete this file once the work is merged.

## Who you're working for

codepint has ADHD. Keep replies short:
- Give the answer first.
- Ask one question at a time.
- Don't add caveats.
- Use the project's own terms (`TriggerRepository`, `ProjectTriggerRepository`, `watch_dir` and so on).

Don't commit or push without their OK. Never open PRs for this work.

## Where things stand

- The webserver routes have been rewritten to the layout in **ADR 0019 section 11** (`project/decisions/0019-global-resources-and-shared-pull-requests.md`). Read that section first. The fan-out and cursors are in ADR 0021, the state tables in ADR 0022 and the Dagster sensors in ADR 0023 (`project/decisions/`); where 0019 is thinner, those win.
  - Global resources live under `/global/...`: `datasets`, `secrets`, `repositories/triggers` and `repositories/results`.
  - Project links live under `/projects/:pid/...` and are keyed by the **global** id (a secret's label). `PUT` links a resource (201 the first time, 200 after), `PATCH` changes the link's settings, and `DELETE` unlinks it.
  - Results live under `/projects/:pid/results`.
  - Global resources and links both have `enabled`. Links also have `revoked`, which only an admin can change, through `PATCH`.
  - Healthchecks exist per resource, per project, and as one global `GET /global/healthcheck`.
- The old route tests are deleted. The new shared fixtures are in `webserver/tests/conftest.py`, and `webserver/tests/test_smoke.py` passes.
- **`webserver/tests/TEST_PLAN.md`** is the plan: 9 test files and 83 tests, listing the exact requests, the expected status codes, the fixtures to use, and the traps.

## Your job

Goal: confidence that the happy paths and basic failure cases work. This is **not** full coverage.

1. **Write the tests in `TEST_PLAN.md`.** Use one Haiku subagent per test file, in parallel.
   - Each subagent writes its file, runs **only that file**, and fixes its own test code.
   - Subagents must **not** edit app code or `conftest.py`.
   - A subagent that gets stuck (the plan is unclear, it can't explain a failure, or it suspects an app bug) stops and reports back to you.
2. **Run the whole webserver suite once with a Sonnet agent.** It sorts every failure into **test bug** (fix it) or **app bug** (list it, don't fix it).
3. Report back to codepint: the pass and fail counts, then the app bugs, one line each.

Use Haiku and Sonnet only. Opus isn't needed.

Keep test calls black-box: HTTP requests and assertions on status codes and response bodies only. The webserver may later move to FastAPI, and black-box tests would carry over.

## Rule: filter in the webserver, not in Dagster

Dagster must not fetch lists and filter them in Python. For example, "projects that are enabled", "links that are active" and "PRs in state X" are all filters the webserver should apply, as query options on the list endpoints (like `?active_link=true`). This PR doesn't touch Dagster, but know which filters Dagster needs (see `dagster/app/backend.py` and the sensors), and make sure the routes support them as query options. Any that are missing go in your report.

## Running the tests

The normal route is `webserver/run_tests.sh`, which uses Docker Compose. For quicker runs of single files you need a Postgres and the env vars from `webserver/run_tests.sh`, with `PGHOST` and `PGPORT` pointing at your Postgres:
```
docker run -d --name fn-routes-test-db -e POSTGRES_DB=test_app -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=test_app -p 127.0.0.1:55432:5432 postgres:17-alpine
cd webserver
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
# export the env vars from run_tests.sh, with PGHOST=127.0.0.1 PGPORT=55432
.venv/bin/pytest tests/<file>.py -q -p no:cacheprovider --no-cov -W ignore
```
`--no-cov` skips the coverage that `setup.cfg` turns on.

## Known issues (don't chase these)

- **`test_dtos.py`:** 2 stale tests. The dataset output now has `enabled`, and its `url` is `/global/datasets/<id>`. Fix them, since they're tiny.
- **Contract fixtures:** `dagster/fncli/tests/test_contract_fixtures.py` was deleted (it read the deleted `webserver/tests/contracts/`). `dagster/app/tests/test_contract_fixtures.py` and `scripts/sync_contract_fixtures.sh` are now unused. Leave them alone.
- **Dagster and fncli tests:** most still use the old routes. That's out of scope here.

App behaviour the plan's author flagged. Don't fix any of it; just confirm or deny it in your report:
- (Outdated) Ingest no longer creates triggers for disabled projects: fan-out skips a link whose project is disabled or revoked (`accepts_triggers`, ADR 0021). Confirm or deny that this holds in the tests.
- A duplicate dataset name returns 500. The other global resources return 409.
- `PATCH /global/datasets/:id` returns 202, while every other `PATCH` returns 200.
- Deleting a trigger link that has PRs returns a raw foreign-key 400. It should be a 409.
- `PATCH /global/secrets/:label` has no admin-only check.
- The secret `PATCH` sets `updated_at` from local time.

## Parked (don't start)

- The Dagster ingest redesign is built (ADR 0023); only the open items listed there are parked.
- Enabled and backfill guard questions (the project lock and drain checks are gone).
- Moving the webserver to FastAPI.
