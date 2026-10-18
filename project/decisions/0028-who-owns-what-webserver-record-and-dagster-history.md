# 0028. Who owns what: the webserver record and Dagster's history

- Status: Accepted (built), with authentication and authorization deliberately deferred ([0014](0014-dar-rename-and-detached-auth.md)). Replaces the last section of [0019](0019-global-resources-and-shared-pull-requests.md), "Who owns what", and its note on locked versus off.

## Context

Two systems hold state about the same work. The webserver has projects, links, pull requests, tasks and results in Postgres. Dagster has runs, ticks and logs in its own database. Without a rule for which one is true, a status gets written from both sides and the two drift ([0017](0017-task-status-written-by-run-status-sensors.md)). Authentication is being reworked elsewhere, so the decision also has to say what is and is not secured today.

## Decision

**The webserver owns the record.**
- The business record (projects, links, pull requests, triggers, tasks, results), the rules (which transitions are allowed, whether a link is active, whether a task's configuration is still current) and the audit table (`@audit` in `webserver/app/helpers/wrappers.py`, `GET /audit` in `admin_api.py`).
- The rules live in the webserver so every client gets the same answer: the spec match rule (`helpers/spec_files.py`), fan-out (`helpers/pull_request_fanout.py`), configuration checks (`helpers/task_config.py`), transition tables ([0026](0026-state-transition-tables.md)).
- Dagster does not decide these. It asks, with a query option or a dedicated route, and acts on the answer ([0027](0027-dagster-pipeline-ops-sensors-and-retries.md)).

**Dagster owns operational history.** Runs, ticks, logs and run tags in Dagster's own database (`dagster/dagster.yaml`). A task carries only `executor_run_id` and the timestamps the run-status sensors copy. Dagster's own materialisations are not used; if added later they would be a read-only mirror of the record, never a source of it.

**The dependency runs one way: Dagster calls the webserver.**
- Every sensor and op reaches the webserver through `BackendAPI` (`dagster/app/backend.py`), logged in as the Dagster system user (`DAGSTER_KC_USER`, `DAGSTER_KC_PASSWORD`, `BackendConfig` in `dagster/app/config.py`). It has the Keycloak realm role `System` (created by `create_system_user` in `build/kc-init/common.py`).
- The webserver does not trigger runs or read Dagster's data. The only code that calls Dagster is `webserver/app/helpers/dagster.py` and `dagster_api.py`: GraphQL `startSensor`, `stopSensor` and a list of sensors with their latest tick, behind `DAGSTER_WEBSERVER_URI`, on admin-only routes `GET|PATCH /dagster/sensors[/<name>]`. That is an operator convenience for switching sensors on and off; no pipeline step depends on it.
- The pipeline is event-driven: sensors react to webserver state, so waiting (a project off or locked, a failed delivery) costs nothing and needs no message to Dagster.

**Locked versus off for a project** (see [0025](0025-switching-off-revoking-and-soft-delete.md) for the full table).
- Locked pauses evaluation and keeps the backlog: the evaluate sensor asks for `locked=false` projects, `POST /projects/<id>/tasks` returns 409, and triggers already created run after unlocking. The lock also guards creating a results link (`helpers/project_lock.py`, `require_locked`).
- Off drops the gap: fan-out skips a disabled project (`ProjectTriggerRepository.accepts_triggers`), and turning it on moves each link's cursor to now (`skip_gap`, called in `projects_api.py` `patch_project`), so pull requests merged meanwhile get no trigger. The launcher skips a disabled project (`get_projects(enabled=True)`).

**Authentication is deferred, with a narrow scope.**
- In scope now: the super user and the Dagster system user. Out of scope: audit permissions, normal-user permissions, dataset-level authorisation, DAR checks.
- `@auth(scope=...)` (`wrappers.py`) still runs on every route, but the `System` role bypasses the permission check (`helpers/keycloak.py` `is_token_valid`, marked `FIXME`), so the Dagster user passes every scope.
- Known gaps:
  - `g.caller_is_admin` is `"Administrator" in realm_access.roles` (`Keycloak.is_user_admin`). The `System` role does not count, so the Dagster user is refused on the admin-only `revoked` field (`project_trigger_repositories_api.py`, `projects_api.py`) and on the revoke-all routes (`helpers/revoke.py`, `UnauthorizedError`).
  - Dagster-only routes (task PATCH, batch ingest, result writes) are open to any admin (G3 in the auth plan; not re-checked route by route).
  - `tasks_api.py` `does_user_own_task` is a hand-written admin-or-owner-or-system check marked `TODO(auth)`.
  - The git token read in delivery is marked `TODO(auth)` (`dagster/app/delivery/results.py`).
- The fuller list is in `project/auth-mvp-plan.md` (G1 to G14).

**fncli is the dev and ops client** ([0015](0015-fncli-dev-ops-tool.md)). It is a second package in `dagster/pyproject.toml`, imports `app.*` (models, `BackendAPI`/`BackendSession`, `EnvConfig`, `git_uri`) rather than copying them, and subclasses `BackendAPI` as `FncliBackendAPI` (`dagster/fncli/backend.py`). It logs in as the same Dagster system user, reading `dagster-keycloak-creds` from the cluster (`build_backend_api` in `dagster/fncli/cmds/common.py`).

## Consequences

- One place answers "is this allowed" and "what is the status"; Dagster can be rebuilt without losing the record.
- A fresh Dagster database loses run history but not tasks or results.
- Because fncli shares `app.*`, a model change in `dagster/app/models` breaks fncli at import or test time, not silently.
- Until auth is reworked, role checks are not a security boundary for non-admin callers ([0014](0014-dar-rename-and-detached-auth.md)).

## Alternatives considered

- **Dagster owns task status, the webserver polls it**: rejected in 0017; Dagster's vocabulary does not carry the business states.
- **The webserver launches runs**: rejected; it would need Dagster's API and would duplicate the sensors' retry logic.
- **Dagster materialisations as the result record**: not done; the record must outlive Dagster.
- **Give the Dagster user the `Administrator` role** to pass `caller_is_admin`: not done; it would let a pipeline credential revoke grants.

## Where it lives

- PR #560, branch `split/06-docs` (this ADR and the docs). The behaviour is implemented across the stack: PR #557 (`split/03-dagster`) for Dagster, and the webserver, chart and fncli branches of the same split.
- Webserver: `webserver/app/helpers/wrappers.py`, `helpers/keycloak.py`, `helpers/revoke.py`, `helpers/dagster.py`, `dagster_api.py`, `projects_api.py`.
- Dagster and fncli: `dagster/app/backend.py`, `dagster/app/config.py`, `dagster/fncli/cmds/common.py`, `dagster/fncli/cmds/sensor.py`.

## Not built or open

- `fncli link-set --revoked` goes as the Dagster `System` user, which `caller_is_admin` rejects (403). The e2e scenarios that revoke a link (S6, S5b, S10 in `dagster/fncli/tests/e2e/test_failure_paths.py`) fail for that reason, as the first live run on 2026-10-18 showed. The fix on branch `moonshot/e2e-run1-fixes` (not merged) lets fncli log in as an admin via `FNCLI_ADMIN_USER` and `FNCLI_ADMIN_PASSWORD`. The alternative, accepting `System` in `caller_is_admin`, would let a pipeline credential revoke grants and is not made.
- 0019 says the webserver "does not know Dagster". It does, for the sensor routes above.
- Materialisation mirroring does not exist.
- Open: should `/dagster/sensors` move out of the webserver so the one-way rule holds without an exception?
