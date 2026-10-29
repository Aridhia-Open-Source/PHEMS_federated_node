# 0023. FastAPI replaces Flask: nexus-api owns the deploy, the migrations and the names

## Context

The Federated Node API was a Flask app in `webserver/`. nexus-api (`nexus/api`) is a FastAPI port of it, with every router ported and the same wire contract. For a time both ran: Flask owned the Deployment and Service `backend`, served at `/`, the alembic migrations and the CI image (`federated_node_run`), and nexus-api ran beside it at `/nexus`, borrowing the backend's ConfigMap and ClusterRole, with no image built by CI. Two APIs on one database, each with its own copy of the rules, is not what [0021](0021-nexus-api-owns-the-record-and-the-rules.md) describes. The node is in beta with no existing installs, so names can change without a compatibility step.

## Decision

**One API: nexus-api, in FastAPI.** Flask and `webserver/` are deleted.
- All the routers are ported: main (login, token refresh, health and ready checks), projects, datasets, tasks, results, users, trigger repositories, project trigger repositories, secrets, git providers, results repositories, Dagster and the health checks. Errors, validation (400), pagination and the route layout keep the Flask contract ([CONTRACT.md](../../nexus/api/CONTRACT.md)).
- Responses are built by the same Pydantic DTOs as before ([0016](0016-pydantic-dto-layer.md)); FastAPI turns them into an OpenAPI spec (`/openapi.json`, committed as `nexus/api/openapi.json`) that the UI generates its types from.
- Each request gets its own database session scope from a middleware, in place of Flask-SQLAlchemy's app context.
- The registries, whitelisted images, DAR, audit and admin extras are not ported: they were already out of scope ([0017](0017-authorization-detached-from-dar-and-keycloak.md)), and what they are for is an open question below. The API-request trigger routes are not implemented yet; tasks come from pull request triggers only.

**nexus-api owns the deploy.** The Deployment, Service, HTTPRoute, ServiceAccount and ClusterRole are all `nexus-api`, served at `/` on the host. The `/nexus` prefix and the `nexus.api.enabled` flag are gone: it is always on. CI builds the image `ghcr.io/aridhia-open-source/nexus_api` from `nexus/api`, and promotes it with the other images on a release.

**nexus-api owns the migrations.** `alembic.ini` and `migrations/` live in `nexus/api`, and the `db-migrations` init container runs `python -m alembic upgrade head` from `/nexus` (after `wait-for-db` when the chart runs Postgres).
- There is one migration until release. `001_baseline.py` is regenerated from the models and is the only file in `versions/`; the Flask-only tables (`audit`, `registries`, `whitelisted_images`, `dars`) are not in it. A branch that changes the schema regenerates it (`alembic revision --autogenerate` against an empty database, keeping the revision id `001_baseline`) instead of adding `002`, and a merge conflict in it is resolved by regenerating, never by hand.
- `nexus/api/tests/test_migrations.py` runs `upgrade head` on an empty database, `alembic check` (no difference from the models) and `downgrade base`.

**The names follow.** "Webserver" in the Flask sense is nexus-api in code, chart and docs. The Dagster webserver (`DAGSTER_WEBSERVER_URI`, `fnDagster.webserver`, `*-dagster-webserver`) is a different thing and keeps its name.

| Was | Is |
|---|---|
| Deployment, Service, route `backend`; service account `secret-backend-handler` | `nexus-api` for all of them |
| Image `federated_node_run`, built from `webserver/` | `nexus_api`, built from `nexus/api` |
| `BACKEND_API_URI` (Dagster) and `BACKEND_URL` (fncli, scripts) | `NEXUS_API_URL` |
| `BACKEND_DB_USER`, `BACKEND_DB_PASSWORD`, `BACKEND_DB_NAME` | `NEXUS_DB_USER`, `NEXUS_DB_PASSWORD`, `NEXUS_DB_NAME` |
| Helm `backend.*` | `nexus.api.*`: image, tag, port, replicas, url, `db.{name,user,secret}` |
| Database and role `backend`, `backend_admin`; secret `backend-db`; job `backend-db-init` | `fn_nexus`, `fn_nexus`; `nexus-db`; `nexus-db-init` |
| `scripts/backend_login.sh` | `scripts/nexus_login.sh` |

**The dev loop and CI follow.** Tilt builds `nexus-api-fn` with `uvicorn --reload`, syncs `nexus/api/app`, rebuilds when `migrations/` or `alembic.ini` change and forwards `localhost:5000` ([0020](0020-tilt-dev-loop.md)). CI lints and tests nexus/api, runs the Keycloak integration tests that now live in `nexus/api/integration_tests/`, and builds `nexus_api`.

## Consequences

- One implementation of the rules, one image and one set of migrations; the chart runs one API on the database.
- A cluster installed from the old chart is reinstalled, not upgraded: the Deployment, database, role and secret names changed.
- `nexus.api.url` (default `http://nexus-api.<namespace>.svc:<port>`) is the one address Dagster, fncli and the smoke tests use.
- Any branch that changes the schema regenerates `001_baseline.py` and carries no `002+` file until the first release.

## Alternatives considered

- **Keep Flask for the deploy and migrations, with nexus-api beside it at `/nexus`:** two implementations of the rules and a borrowed ConfigMap and ClusterRole.
- **Keep the `backend` names and the `/nexus` prefix:** the names would describe neither the service nor its place, and the UI is to be `nexus-ui`.
- **Carry the Flask migration history forward and add `002+` for the changes:** the history holds tables the models no longer have, and there is no install to upgrade, so one regenerated baseline is simpler.
- **Leave `alembic.ini` and `migrations/` in `webserver/`:** a Flask directory kept alive only to migrate the database of the app that replaced it.

## Open questions

The extras were left out on purpose, not forgotten. Before any of them is built we need to understand its purpose, what clients are trying to accomplish with it, whether it is needed at all and whether the node should own it, rather than port a half-built implementation.

- Registries: what they are for, and whether the node should own them.
- Whitelisted images: what they are for, and whether the node should own them.
- DAR: what it is for, and whether the node should own it ([0017](0017-authorization-detached-from-dar-and-keycloak.md)).
- Audit: what it is for, and whether the node should own it.
- Admin endpoints: what clients are trying to accomplish with them, and whether the node should own them.
- When the first release freezes the baseline, and from which change migrations are added in sequence.
