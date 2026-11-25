# Plan: postgres service config (fednode/5, #762)

Status: complete. The final chart retains the shared server settings under `db.*`; Keycloak uses `keycloak.db.*`, and Dagster uses `dagster.postgresql.*`.
- The chart keeps one PostgreSQL server for the components. `create_db_deployment` controls the in-cluster
  `db-internal` deployment; `db.host`, `db.port`, `db.enforceSSL`, `db.superuser` and
  `db.manageRolesAndDatabases` describe the server and its administration.
- Each component owns its database and credentials: `nexus.api.db.*`, `keycloak.db.*`, and
  `dagster.postgresql.*` (the Dagster subchart's names). Dagster's host and port default to `db.host` and
  `db.port`, while its database name, user and password secret come from the `dagster` block.
- Shared helpers resolve the database host and port. Init jobs create or check each component's database and role,
  and the requirements check rejects mismatched Dagster host/port values when the chart manages the server.
- nexus-api reads `DATABASE_*` from the unified settings.
- Cases: in-cluster (`create_db_deployment: true`), external PostgreSQL, and DBA-managed roles and databases
  (`db.manageRolesAndDatabases: false`, with a check hook verifying the supplied credentials).
