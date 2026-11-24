# 0039. Fednode shared package

Status: Proposed, 2026-11-24. Supersedes 0038 (one outbound client layer for nexus-api).

## Context

nexus-api, Dagster, the operator, fncli and kc-init each call the same systems: nexus-api, Keycloak, Dagster,
Kubernetes and the git providers. Each had its own copy of the client code, with its own timeouts, retries and error
types. `nexus_client` (in `nexus/client`) already shared the nexus-api client between Dagster, fncli and the operator,
but nexus-api kept a separate outbound layer (0038) because depending on `nexus_client` seemed too heavy for about 60
lines. Since then the copies have grown: Keycloak logins, Dagster clients, git clients and mounted secret readers
each exist in more than one service.

Settings drifted the same way. Each service read env vars under its own names (`NEXUS_API_URL`, `DAGSTER_KC_*`,
`OPERATOR_KC_*`, `KEYCLOAK_*`, `PGHOST`, `NEXUS_DB_*`), so the same setting had several names, and chart values did
not say which component a value belongs to.

## Decision

- One shared package, `fednode` (today's `nexus/client` and `nexus_client`, renamed and flattened: no doubled
  `fednode/fednode` folder). nexus-api, Dagster, the operator, fncli and kc-init install it as a path dependency.
- What goes in:
  - transport, `fednode/http.py`: `HttpClient`, `RetryAdapter`, `ClientError`, `ClientTimeout`;
  - clients, `fednode/clients/`: `nexus` (client and its response models), `keycloak` (login, admin, signing keys),
    `dagster`, `kubernetes` (one client, `in_cluster` or `kubeconfig`; `MountedSecret`; name helpers),
    `git` (`GitProvider`, GitHub, Gitea, `GitUri`);
  - shared settings, `fednode/settings.py`;
  - fncli, as `fednode/cli`, behind the `cli` extra, so services do not install its dependencies.
- What never goes in: business rules, nexus-api models or DTOs, or anything that decides (0021). The package talks to
  systems; the services decide what to do with the answers.
- Callers catch `ClientError` and `ClientTimeout`, never `requests` exceptions.
- `HttpClient` is the outbound layer for every service, nexus-api included. It keeps 0038's rules: a default
  `(connect, read)` timeout (3s, 10s) a service or a call can override; only a 429 is retried, 3 times with backoff,
  honouring `Retry-After`, for every method; a read timeout is never retried; shared sessions carry no cookies and no
  `Authorization` header of their own.
- Settings convention:
  - Every settings class in every service builds on `fednode.settings.EnvSettings`.
  - Shared settings classes (`NodeSettings`, `NamespacesSettings`, `HttpSettings`, `DatabaseSettings`,
    `NexusSettings`, `DagsterSettings`, `KeycloakSettings`) have every field optional. A service makes a field
    required by redeclaring it with a plain type (`uri: str`), or overrides its default.
  - The env name is the settings path in capitals, dots to `_`: `settings.tasks.limits.max_cpu` reads
    `TASKS_LIMITS_MAX_CPU`. Each class sets `env_prefix`; no aliases, and no per-service prefix (env vars are per
    container).
  - `services.*` holds the systems a service calls but does not own (nexus, dagster, keycloak); `database` is the
    database it owns, at the top level.
  - Chart values carry the owner: `nexus.database.name` becomes nexus-api's `DATABASE_NAME`.
  - Exceptions, names we do not control: the Dagster chart's `dagster.postgresql.*` and Keycloak's `KC_DB_*`.

## Consequences

- One copy of each client: a timeout, retry or error type changes in one place for every service.
- 0038's concern, that two outbound layers drift, goes away; its rules live in `fednode/http.py`.
- Every image build context includes the package, and each service pins it through pip-compile.
- The env renames touch every chart configmap and every dev env file at once; there are no compatibility aliases
  (beta).
- A setting reads the same way in every service, and its chart value says which component owns it.
- fncli ships in the same package, so a client change and the CLI that uses it land together.

## Alternatives considered

- No shared code, only a naming convention: keeps the copies and their drift; rejected.
- Shared clients, settings in each service only: the same setting keeps several names across services; rejected.
- Aliases per field to keep the old env names: hides which name is real and doubles the lookup; rejected (beta, no
  compatibility needed).
- A separate outbound package for nexus-api (0038's revisit): two packages for one job; rejected.

## Open questions

- None.
