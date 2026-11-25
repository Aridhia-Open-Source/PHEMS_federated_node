# Plan: postgres service config (fednode/5, #762)

Status: not started.
- One name: Service and Deployment `postgres` (were `db`, `db-internal`); values `postgres.*` (were `db.*`) = the default
  server: `create`, `host`, `port`, `ssl`, `admin.{user,passwordSecret}`, `manageDatabases`.
- Each component owns its database: `nexus.database.*`, `keycloak.database.*`; Dagster via `dagster.postgresql.*`
  (its chart's names) plus `dagster.database.admin`. `host`/`port`/`ssl`/`admin` fall back to `postgres.*`.
- One helper resolves the fallback; init jobs connect to each component's own server with its admin; requirements-check
  compares Dagster's subchart host with Dagster's own database host.
- nexus-api reads `DATABASE_*` (from the unified settings PR).
- Cases: in-cluster (`create: true`), one existing server, split servers (set `host` on the odd one out), DBA-managed
  (`manageDatabases: false`, a check job verifies the logins).
