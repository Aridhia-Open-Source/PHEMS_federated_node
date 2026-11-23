# What changed since `develop`

`develop` is the 1.x line: a Flask API, a task controller and a backend. `dagster-develop` is the 2.x beta, a different shape; the table says what 2.x does. Anything a tester knew about 1.x should be re-checked. The decision records (`project/decisions/`) give the reasons; this page gives the list.

| Area | 2.x beta (`dagster-develop`) | Decisions |
|---|---|---|
| API | nexus-api (FastAPI) owns the record and the rules; responses are built through DTOs; state changes follow transition tables, a refused move is a 409 | 0023, 0016, 0021, 0005 |
| Running tasks | Dagster pipelines: sensors ingest merged pull requests, launch one task per pull request, retry and track runs | 0014, 0015, 0011, 0012 |
| Tasks | Polymorphic triggers and task specs; a task is pinned to the configuration it started with | 0001, 0002, 0009 |
| Results | Delivered as a pushed branch plus a results pull request; task success does not depend on delivery | 0013, 0003, 0004 |
| Records | Global and project resources, secret providers, enabled/revoked and soft delete | 0006, 0007, 0008 |
| Git access | GitHub App tokens minted by the backend; Gitea supported | 0024, 0019 |
| Isolation | Task pods run in their own namespace with default-deny network egress | 0022 |
| Dev tools | `fncli` (apply, diff, delete, demo, trigger, start-sensor), experiments with their own database and seed, the Tilt loop, `docker buildx bake` images | 0018, 0025 to 0028, 0030, 0020, 0029 |
| Deployment | One Helm chart: Traefik gateway, Keycloak, Postgres, Dagster; Gitea optional. Runs behind a TLS-intercepting proxy or a private CA | 0033 |
| UI | nexus-ui, a React admin UI for the API |  |

## What this means for testing

- Anything that talked to the task controller or the backend is gone; test the Dagster flow instead (pull request, sensor, run, results pull request).
- Ownership and access were reworked: see [incoming-changes.md](incoming-changes.md) for the auth work that is still landing.
- Node config is applied with `fncli apply` today; the operator replaces that with `kubectl apply` (see [incoming-changes.md](incoming-changes.md)).
- The 1.x docs are kept under `docs/versions/1.x`; the 2.x wiki is under `docs/versions/2.x`.
