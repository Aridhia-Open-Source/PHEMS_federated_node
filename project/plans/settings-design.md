# Unified settings, shared package and Postgres naming (plan, 2026-11-24)

Status: agreed in chat with codepint, NOT started. Do not start without an explicit go.

## Rules
- One shared package `fednode` (today's `nexus/client`, from the shared client PR), flattened (no `nexus/fednode/fednode`).
- Every settings class in every service builds on `fednode.settings.EnvSettings`.
- Shared settings classes live in `fednode` with every field optional; a service makes a field required by redeclaring it
  with a plain type (`uri: str`), or overrides a default. No aliases.
- Env name = the settings path in capitals, dots to `_` (`settings.tasks.limits.max_cpu` <- `TASKS_LIMITS_MAX_CPU`).
  Each class sets `env_prefix`; no per-service prefix (env vars are per container).
- Chart values carry the owner: `<component>.<path>` (`nexus.database.name` -> nexus-api pod `DATABASE_NAME`).
- `services.*` = systems a service calls but does not own (nexus, dagster, keycloak). `database` = owned, top level.
- Big settings modules are split into a `settings/` package per service; small shared ones stay one file.
- Exceptions we can't change: Dagster chart's `dagster.postgresql.*` names, Keycloak's `KC_DB_*`.

## Shared package
```
fednode/
├─ http.py          HttpClient, RetryAdapter, ClientError, ClientTimeout
├─ settings.py      EnvSettings, NodeSettings, NamespacesSettings, HttpSettings, DatabaseSettings,
│                   NexusSettings, DagsterSettings, KeycloakSettings          (all fields optional)
└─ clients/
   ├─ nexus/        client.py (NexusClient), models/
   ├─ keycloak/     login.py (KeycloakLogin), admin.py (KeycloakAdmin), keys.py (KeycloakKeys)
   ├─ dagster/      client.py (DagsterClient)
   ├─ kubernetes/   client.py (KubernetesClient, in_cluster | kubeconfig), mounted.py (MountedSecret), names.py
   └─ git/          provider.py (GitProvider), github.py, gitea.py, uri.py (GitUri)
```

## Settings trees (! = required in that service)
```
nexus-api                                   (nexus/api/app/settings/)
├─ node              (shared)   id, hostname!                              NODE_*
├─ namespaces        (shared)   tasks!, secrets!, quarantine               NAMESPACES_*
├─ http              (shared)   connect_timeout = 3, read_timeout = 10     HTTP_*
├─ services
│    dagster         (shared)   uri!                                       SERVICES_DAGSTER_*
│    keycloak        (shared)   url!, realm, client, admin, service_user, secrets_path,
│                               token_cache_ttl, login_attempts, login_backoff   SERVICES_KEYCLOAK_*
├─ tasks
│    limits                     max_cpu!, max_memory!, default_limit_cpu!, default_limit_memory!   TASKS_LIMITS_*
└─ database          (shared)   host!, port!, name!, user!, password!, ssl DATABASE_*

dagster                                     (dagster/app/settings/)
├─ node              (shared)   id!, hostname                              NODE_*
├─ namespaces        (shared)   deployment!, tasks!                        NAMESPACES_*
├─ http              (shared)                                              HTTP_*
├─ services
│    nexus           (shared)   uri!, user!, password_file!                SERVICES_NEXUS_*
├─ artifacts                    pvc_name!, mount_path!                     ARTIFACTS_*
├─ tasks                        active_deadline_seconds!                   TASKS_*
│    security                   fs_group, run_as_user, run_as_group, supplemental_groups   TASKS_SECURITY_*
├─ results                      max_zip_bytes = 10 MB, max_attempts = 5    RESULTS_*
└─ sensors                      initial_status, min_interval_seconds = 30, retry_interval_seconds = 60   SENSORS_*

operator                                    (nexus/operator/nexus_operator/settings/)
├─ node              (shared)   id, hostname                               NODE_*
├─ http              (shared)                                              HTTP_*
├─ services
│    nexus           (shared)   uri!, user!, password_file!                SERVICES_NEXUS_*
└─ reconcile                    interval_seconds = 60, retry_delay_seconds = 60   RECONCILE_*
```

## Postgres in the chart
- One name: Service and Deployment `postgres` (were `db`, `db-internal`); values `postgres.*` (were `db.*`).
- `postgres.*` = the default server: `create`, `host`, `port`, `ssl`, `admin.{user,passwordSecret}`, `manageDatabases`.
- Each component owns its database: `nexus.database.*`, `keycloak.database.*`; Dagster via its chart's
  `dagster.postgresql.*` plus `dagster.database.admin`. `host`/`port`/`ssl`/`admin` default to `postgres.*`.
- A helper resolves the fallback once per component. Init jobs connect to each component's own server with its admin.
- Cases: in-cluster (create: true), one existing server (create: false, host set), split servers (host on the odd one out),
  DBA-managed (manageDatabases: false, a check job verifies the logins).
- requirements-check compares Dagster's subchart host with Dagster's own database host.

## Env renames (chart configmaps change in the same commits)
| Today | New |
|---|---|
| `PUBLIC_URL` | `NODE_HOSTNAME` |
| `TASK_NAMESPACE`, `DAGSTER_TASK_NAMESPACE` | `NAMESPACES_TASKS` |
| `SECRETS_NAMESPACE`, `QUARANTINE_NAMESPACE`, `DAGSTER_DEPLOYMENT_NAMESPACE` | `NAMESPACES_SECRETS`, `NAMESPACES_QUARANTINE`, `NAMESPACES_DEPLOYMENT` |
| `OUTBOUND_CONNECT_TIMEOUT`, `OUTBOUND_READ_TIMEOUT` | `HTTP_CONNECT_TIMEOUT`, `HTTP_READ_TIMEOUT` |
| `NEXUS_API_URL`, `DAGSTER_KC_*` / `OPERATOR_KC_*` | `SERVICES_NEXUS_URI`, `SERVICES_NEXUS_USER`, `SERVICES_NEXUS_PASSWORD_FILE` |
| `DAGSTER_WEBSERVER_URI` | `SERVICES_DAGSTER_URI` |
| `KEYCLOAK_*`, `KC_SECRETS_PATH` | `SERVICES_KEYCLOAK_*` |
| `TASK_COMPUTE_*` | `TASKS_LIMITS_*` |
| `PGHOST`, `PGPORT`, `DB_SSL`, `NEXUS_DB_*` | `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_SSL`, `DATABASE_NAME`/`USER`/`PASSWORD` |
| `DAGSTER_ARTIFACTS_PVC_NAME`, `DAGSTER_ARTIFACT_MOUNT_PATH` | `ARTIFACTS_PVC_NAME`, `ARTIFACTS_MOUNT_PATH` |
| `DAGSTER_TASK_ACTIVE_DEADLINE_SECONDS`, `DAGSTER_PIPES_*` | `TASKS_ACTIVE_DEADLINE_SECONDS`, `TASKS_SECURITY_*` |
| `DAGSTER_DELIVERY_MAX_ATTEMPTS` | `RESULTS_MAX_ATTEMPTS` |
| `DAGSTER_SENSORS_*` | `SENSORS_*` |
| `OPERATOR_SYNC_INTERVAL_SECONDS`, `OPERATOR_RETRY_DELAY_SECONDS` | `RECONCILE_INTERVAL_SECONDS`, `RECONCILE_RETRY_DELAY_SECONDS` |

## Where it lands
| Position | PR (xo) | Change |
|---|---|---|
| refactor/5 (new) | routers by URL scope, auth and probe routes, health checks per resource (T-128, draft #763) | `auth_api.py`, probes in `healthcheck_api.py`, `app/health/`, `app/globals/` and `app/projects/` |
| refactor/6 (moved from operator/2) | shared client (T-043) | `nexus/client` becomes `fednode`; shared clients (HTTP, Keycloak, Dagster, Kubernetes, git) move in and services switch to them. If too big: package rename as pure moves, then nexus-api's own clients onto the shared ones |
| refactor/7 | settings, nexus-api + Dagster (T-119, PR #742; #743/T-108 folded in and closed when work starts) | shared settings classes in `fednode/settings.py`; `app/settings/` packages for nexus-api and Dagster; new env names; their chart values and configmaps |
| refactor/8 (new) | Postgres naming and per-component databases (new ticket) | `db`/`db-internal`/`db.*` to `postgres`, per-component database values, fallback helper, init jobs, checks |
| operator/3 | operator core (T-039) | operator `settings/` on fednode, `reconcile`, new env names |
| above | auth, authorization, operator stacks | rebuilt; one test run; one push |

Notes: the paused review-comments agent's unpushed work (scratch worktree `fx3/wt`) is rebased onto this.
`DATABASE_SSL` keeps today's string format; the redesign stays in the database TLS draft PR.

## ADR
- ADR 0039 (#765) supersedes ADR 0038 (outbound client layer); remove 0038 and repoint its references when 0039 is written.
