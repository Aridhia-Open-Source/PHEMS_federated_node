# Handover: open items and working notes

Read the decision records first ([project/decisions](project/decisions/README.md)); they win where this file differs. The index of all docs is [docs/README.md](docs/README.md).

## Routes

The webserver routes follow the layout in ADR 0006, "URL layout" ([0006](project/decisions/0006-global-resources-and-project-links.md)). The flags and soft delete are in ADR 0008, task pinning in ADR 0009, the fan-out and cursors in ADR 0011, the state tables in ADR 0005 and the Dagster sensors in ADR 0014.

- Global resources live under `/global/...`: `datasets`, `secrets`, `repositories/triggers` and `repositories/results`.
- Project links live under `/projects/:pid/...` and are keyed by the global id (a secret's label). `PUT` links a resource (201 the first time, 200 after), `PATCH` changes the link's settings, and `DELETE` unlinks it.
- Results live under `/projects/:pid/results`.
- Global resources and links both have `enabled`. Links also have `revoked`, which only an admin can change, through `PATCH`.
- Healthchecks exist per resource, per project, and as one global `GET /global/healthcheck`.

[webserver/tests/TEST_PLAN.md](webserver/tests/TEST_PLAN.md) lists the requests, the expected status codes and the fixtures of the webserver route tests. The tests are black-box: HTTP requests and assertions on status codes and response bodies only.

## Rule: filter in the webserver, not in Dagster

Dagster does not fetch lists and filter them in Python. "Projects that are enabled", "links that are active" and "PRs in state X" are filters the webserver applies as query options on the list endpoints (like `?active_link=true`). A filter Dagster needs that a route lacks is added to the route.

## Running the webserver tests

The normal route is `webserver/run_tests.sh`, which uses Docker Compose. For quicker runs of single files, start a Postgres and set the env vars from `webserver/run_tests.sh`, with `PGHOST` and `PGPORT` pointing at it:

```
docker run -d --name fn-routes-test-db -e POSTGRES_DB=test_app -e POSTGRES_USER=admin \
  -e POSTGRES_PASSWORD=test_app -p 127.0.0.1:55432:5432 postgres:17-alpine
cd webserver
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest tests/<file>.py -q -p no:cacheprovider --no-cov -W ignore
```

`--no-cov` skips the coverage that `setup.cfg` turns on. The end-to-end suites are described in [dagster/fncli/tests/e2e/README.md](dagster/fncli/tests/e2e/README.md).

## Known issues

- `dagster/app/tests/test_contract_fixtures.py` and `scripts/sync_contract_fixtures.sh` are unused: the contract fixtures they read are gone.
- A duplicate dataset name returns 500; the other global resources return 409.
- Deleting a trigger link that has PRs returns a raw foreign-key 400 instead of a 409.
- `PATCH /global/secrets/:label` has no admin-only check, and sets `updated_at` from local time.
- Dataset `PATCH` returns 200 and `GET /tasks` clamps `page` and `per_page` below 1; both are listed as open questions in ADR 0006.
- `fncli link-set --revoked` logs in as the first Keycloak user (an Administrator), because the Dagster `System` user is refused (403). Set `FNCLI_ADMIN_USER` and `FNCLI_ADMIN_PASSWORD` in `.dev.env`.
- The `keycloak-realm-init` pod can crash-loop after deploy on realm migration 2 (a 400, "client profile contains the executor which does not have valid provider"); the e2e suites still run.
- A task that goes STARTED to SUCCESS between two sensor ticks gets `started_at` from the run record's `start_time`; whether Dagster fills it for such a run is unconfirmed.
- The S11 e2e check reads the tick error's `stack` and `causes`; that the Dagster GraphQL `PythonError` carries "Ingest failed" there is unconfirmed.
- The disabled check and the results link are two steps, and `post_task` does not check that the project is enabled ([0008](project/decisions/0008-enabled-revoked-and-soft-delete.md)).
- The ingest versus link-create race, and `get_or_assign_*` in fncli returning an existing link with different settings.
- Authentication, audit and normal-user permissions are out of scope until the authorization rework ([0017](project/decisions/0017-authorization-detached-from-dar-and-keycloak.md)); only the super user and the Dagster system user matter.
- Isolation (NetworkPolicy, RBAC, per-task secrets) and the beta issues #536, #537, #538, #539 and #500 are tracked on GitHub.
- The mirror service is developed on branch `moonshot/gitea-mirror`.

## Parked

- Enabled and backfill guard questions (the project lock and drain checks are gone).
- Moving the webserver to FastAPI.
- Redundant remote branches are removed and the tag `shared-resources-tests-full` is pushed from a machine that can delete refs.
