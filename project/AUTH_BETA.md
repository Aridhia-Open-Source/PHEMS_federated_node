# Auth MVP plan: user / admin / system

Research only. No code changed. Paths are in `nexus/api/app/` unless stated. Line numbers are from `moonshot/shared-resources` (read at 95d61117 plus the working tree).

## Short answer

- The existing realm roles already match the three tiers: `Users`, `Administrator`, `System` (plus `Super Administrator`).
- The existing **scopes cannot** express the nesting or "system only". They are a poor fit.
- Recommended: add `@auth(role="user"|"admin"|"system")`. It reads `realm_access.roles` from the token, which `_auth` already decodes. **No realm change, no kc-init migration.**
- Dagster and fncli already log in as a System user (`dagster`). No credential change.
- Zero routes are unauthenticated by accident. About 26 handlers have the wrong role or path for the new model.

## 1. How auth works today

- **Token**: `POST /login` (`main.py:56`) does a password grant on the Keycloak client `global`. It returns a **refresh token**, and clients send that as `Authorization: Bearer`.
- **Decorator**: `auth(scope)` in `helpers/wrappers.py:15`. Per request it does these steps:
  - Refresh the token to an access token (`decode_token`, keycloak.py:409), then introspect it.
  - Look up the user by username.
  - Set `g.caller_is_admin` (`is_user_admin`: is `"Administrator"` in `realm_access.roles`).
  - Call `is_token_valid(token, scope, 'endpoints')` (keycloak.py:~370).
- **Permission check**: `is_token_valid` calls `check_permissions`. That is a Keycloak UMA ticket request for `endpoints#<scope>` with `response_mode=decision`.
- **System bypass**: keycloak.py:398 is `# FIXME: Temporary workaround for system users`. If the token has role `System`, the UMA check is skipped. System passes every scope.
- **Errors**: no token gives 401 (`AuthenticationError`). A failed permission check gives 403 (`UnauthorizedError`). Both are in `helpers/exceptions.py`.
- **Blueprint hooks**: some blueprints run `@bp.before_request @auth(scope=...)`. These cover every route in the blueprint: dagster (`can_do_admin`); git_providers, trigger_repositories, results_repositories and secrets (`can_admin_dataset`). Route-level `@auth` adds to the hook.
- **Realm** (`k8s/federated-node/scripts/realms.json`, same as develop):
  - Realm roles: `Users`, `Administrator`, `Super Administrator`, `System`.
  - Composites: `Administrator` includes `Users`. `Super Administrator` includes `Administrator` and `Users`. `System` includes neither.
  - Client `global` has one authz resource, `endpoints`, with 8 scopes.
  - Role policies: `admin-policy` (Administrator or Super Administrator), `superadmin-policy`, `all-users-policy` (+ Users), `system-policy` (System).
  - Scope permissions:

    | Scope | Policies |
    |---|---|
    | `can_do_admin`, `can_admin_task` | admin-policy |
    | `can_admin_dataset`, `can_admin_request`, `can_transfer_token` | admin-policy + system-policy |
    | `can_exec_task`, `can_access_dataset`, `can_send_request` | all-users-policy + system-policy |

  - In practice there are only two levels. Every admin scope behaves the same. System passes everything through the FIXME.
- **kc-init** (`build/kc-init`): `setup_realm.py` creates the first user (role `Administrator`, `FIRST_USER_*`) and the Dagster user via `create_system_user` (`common.py:477`, role `System`). Realm changes after install need a migration in `migrations/` (m001, m002 exist). `partial_import` skips the existing `global` client, so a scope or policy change needs m003.
- **Legacy `origin/develop`**:
  - The same decorator also did dataset-resource lookup, and per-DAR clients plus token exchange (`models/request.py`, `Keycloak(client)`) for non-admins.
  - On shared-resources this is disconnected (ADR 0017, `TODO(DAR)` at wrappers.py:35).
  - `dagster-develop` added: the `dagster` System user and `dagster-keycloak-creds` secret (+ rotation), `fn-service` (Super Administrator) for backend admin calls, the System bypass, and `is_system_user`.
- **Who calls the API**:
  - Dagster `dagster/app/backend.py` and fncli `dagster/fncli/cmds/common.py:134` both read `dagster-keycloak-creds` (`DAGSTER_KC_USER` / `DAGSTER_KC_PASSWORD`). Both are System.
  - Humans use `/login` with a Keycloak user. The first user is `Administrator`.

## 2. Gap list

| # | Gap | Where |
|---|---|---|
| G1 | System has no scope of its own. It only works through the FIXME bypass. Nothing is system-only. | keycloak.py:398, realms.json |
| G2 | The 3 admin scopes are equivalent. `can_admin_dataset` is used for projects, results, tasks and healthchecks, so it is misnamed. `can_transfer_token`, `can_send_request` and `can_admin_request` have no live route. | realms.json, datasets_api.py:41,118 |
| G3 | Dagster-only routes are open to any admin: task PATCH, PR batch POST, result POST/PATCH, PR PATCH, create-task POST. Note the `TODO: called by Dagster only`. | trigger_repositories_api.py:94-96, tasks_api.py:138, results_api.py:82,130, project_trigger_repositories_api.py:288,306 |
| G4 | `GET /global/datasets` and `/global/datasets/<id>` use `can_access_dataset`. Users pass them, but `/global` should be admin. | datasets_api.py:41,118 |
| G5 | `/audit` and `/delivery-secret` are at the root, not under `/global`. | admin_api.py:27,38 |
| G6 | `g.caller_is_admin` only checks `"Administrator"`, so System counts as not admin. It gates the `revoked` field. | wrappers.py:32, projects_api.py:254,358,479, project_trigger_repositories_api.py:169 |
| G7 | `get_tasks` uses `can_admin_task` (admin only), but it is a project read. `get_result` uses `can_exec_task` while `get_results` uses `can_admin_dataset`. Inconsistent. | tasks_api.py:86, results_api.py:47,70 |
| G8 | A hand-rolled admin-or-owner-or-system check on task read. It is per-user isolation, which the MVP says is out of scope. | tasks_api.py:56-70 |
| G9 | Auth hook plus route decorator on the same route (secrets, providers, trigger repos). `patch_secret` has only the hook. It works but is hard to audit. | secrets_api.py:38,184 |
| G10 | `POST /global/users` defaults the new user's role to `Users` unless the body has `role`. | keycloak.py:757, users_api.py:23 |
| G11 | Each request does several Keycloak calls (service login in `Keycloak()`, refresh, introspect, user lookup, `is_user_admin` introspect, UMA, resource lookup). `audit` decodes the token again. | wrappers.py:28-48,76-80 |
| G12 | Tests mock Keycloak by token string. `is_token_valid` returns true for any user token except scope `can_admin_request`, so no test can show a 403 by role. | tests/conftest.py:664-710 |
| G13 | Disconnected blueprints still carry scopes: `dar_api` (3 handlers) and `whitelisted_images_api` (4). Not registered, so their routes return 404. | `__init__.py:81-83`, dar_api.py:21 |
| G14 | `/docs` (Swagger UI) is public. The `openapi.json` may describe routes that need a role. | `__init__.py:37,69` |

Unauthenticated by design: `/`, `/ready_check`, `/health_check`, `/login`, `/refresh_token` (checks the token itself), `PUT /global/users/reset-password`, `/docs`. Nothing else is unauthenticated, once the blueprint hooks are counted.

## 3. Role design

| Role | Keycloak realm role | Can call |
|---|---|---|
| user | `Users` | project endpoints (reads, tasks), no isolation |
| admin | `Administrator` (Super Administrator includes it) | user + all `/global/...` + project config writes |
| system | `System` | admin + inter-service routes |

- **Nesting in code, not Keycloak.** The caller's roles come from `realm_access.roles` in the introspection result:
  - system routes need `System`.
  - admin routes need `Administrator` or `System`.
  - user routes need `Users`, `Administrator` or `System`.
  - `Administrator` has `Users` via its composite. System is checked explicitly.
- **Decorator:** `@auth(role="admin")`. It decodes the token once and skips the UMA call and the `is_user_admin` introspect.
- **Keep `scope=`** accepted during the change, then delete it once every route is moved.
- **Blueprint hooks:** use `role=` too, `admin` on `/global/*` blueprints and `system` on `/dagster`. A route-level `@auth(role="system")` adds the stricter rule, and the strictest wins.
- **Handlers:** set `g.caller_is_admin` to "role is admin or system" (fixes G6). Optionally cache the decoded token in `g` so `audit` reuses it (G11).
- **Why not realm scopes:** a system-only scope means a new scope, policy and permission on the `global` client plus kc-init m003 (G1). It keeps the extra Keycloak round trips and the System bypass. Only worth it if policy-driven auth is wanted later.
- **Optional realm tidy** (can wait): m003 making `System` a composite of `Administrator`. Not needed for the code approach.

## 4. Route to role table

Current = effective scope after hooks. All handlers on shared-resources (a `/` and `''` route pair counts once). `*` = target differs from today.

**Public**

| Route | Handler line | Current | Target |
|---|---|---|---|
| GET `/`, `/ready_check`, `/health_check` | main.py:16,25,34 | none | public |
| POST `/login`, `/refresh_token` | main.py:56,71 | none | public (refresh checks the token) |
| PUT `/global/users/reset-password` | users_api.py:54 | none | public |
| `/docs` | `__init__.py:37` | none | public (see Q9) |

**Admin: `/global/...`**

| Route | Handler line | Current | Target |
|---|---|---|---|
| GET `/audit` | admin_api.py:27 | can_do_admin | admin (path to `/global/audit`, Q5) |
| PATCH `/delivery-secret` | admin_api.py:38 | can_do_admin | admin (path to `/global/...`, Q5) |
| GET `/global/datasets`, GET `/<id>` | datasets_api.py:42,120 | can_access_dataset | admin * (G4) |
| POST, DELETE, PATCH `/global/datasets` | datasets_api.py:80,131,155 | can_do_admin | admin |
| `/global/providers` GET list, GET one | git_providers_api.py:49,57 | hook can_admin_dataset | admin |
| `/global/providers` POST, PATCH, DELETE | git_providers_api.py:67,86,124 | can_do_admin | admin |
| `/global/registries` list, get, add, patch, delete | registries_api.py:26,36,49,65,81 | can_admin_dataset | admin |
| `/global/users` POST, GET | users_api.py:23,74 | can_do_admin | admin |
| `/global/repositories/triggers` GET list, one, `/pull_requests` GET | trigger_repositories_api.py:48,69,78 | hook can_admin_dataset | admin |
| `/global/repositories/triggers` POST, PATCH, DELETE | trigger_repositories_api.py:146,181,125 | can_do_admin | admin |
| `/global/repositories/results` GET list, one | results_repositories_api.py:39,47 | hook can_admin_dataset | admin |
| `/global/repositories/results` POST, PATCH, DELETE | results_repositories_api.py:78,113,57 | can_do_admin | admin |
| `/global/secrets` GET list, one, PATCH | secrets_api.py:122,130,184 | hook can_admin_dataset | admin |
| `/global/secrets` POST, DELETE | secrets_api.py:141,220 | can_do_admin | admin |
| `/global/healthcheck`, `/datasets/<id>`, `/secrets/<l>`, `/providers/<id>`, `/repositories/triggers/<id>`, `/repositories/results/<id>` (6) | healthcheck_api.py:177,205,216,227,237,248 | can_admin_dataset | admin |
| `/projects/<id>/healthcheck` and its 4 sub-routes (datasets, secrets, trigger repo, results repo) | healthcheck_api.py:259,312,323,334,346 | can_admin_dataset | admin |
| `/global/whitelisted_images` (4) | whitelisted_images_api.py:76,92,128,140 | not registered | admin, when re-attached |
| `/requests` (3) | dar_api.py:30,42,77 | not registered | admin, when re-attached |

**System: inter-service**

| Route | Handler line | Current | Target |
|---|---|---|---|
| POST `/global/repositories/triggers/<id>/pull_requests` (batch ingest) | trigger_repositories_api.py:96 | hook can_admin_dataset | system * |
| PATCH `/projects/<p>/repositories/triggers/<r>/pull_requests/<n>` | project_trigger_repositories_api.py:288 | can_admin_dataset | system * |
| POST `.../pull_requests/<n>/task` | project_trigger_repositories_api.py:306 | can_admin_dataset | system * |
| PATCH `/projects/<p>/tasks/<id>` (status) | tasks_api.py:138 | can_admin_dataset | system * |
| POST `/projects/<p>/results` | results_api.py:82 | can_admin_dataset | system * |
| PATCH `/projects/<p>/results/<id>` | results_api.py:130 | can_admin_dataset | system * |
| `/dagster/sensors` GET list, GET one, PATCH all, PATCH one | dagster_api.py:54,62,71,92 | hook can_do_admin | system * (Q2) |

**Projects: user reads and tasks, admin config**

| Route | Handler line | Current | Target |
|---|---|---|---|
| GET `/projects`, GET `/projects/<id>` | projects_api.py:56,66 | can_admin_dataset | user * |
| POST, PATCH, DELETE `/projects` | projects_api.py:80,96,123 | can_admin_dataset | admin (Q1) |
| `/projects/<id>/datasets` GET list, GET one | projects_api.py:188,201 | can_admin_dataset | user * |
| `/projects/<id>/datasets/<d>` PUT, PATCH, DELETE | projects_api.py:211,240,268 | can_admin_dataset | admin |
| `/projects/<id>/secrets` GET list, one, PUT, PATCH, DELETE | projects_api.py:290,303,313,344,372 | can_admin_dataset | admin |
| `/projects/<id>/repositories/results` GET list, one | projects_api.py:399,412 | can_admin_dataset | user * |
| `/projects/<id>/repositories/results/<r>` PUT, PATCH, DELETE | projects_api.py:422,464,500 | can_admin_dataset | admin |
| `/projects/<p>/repositories/triggers` GET list, GET one | project_trigger_repositories_api.py:65,144 | can_admin_dataset | user * |
| `/projects/<p>/repositories/triggers/<r>` PUT, PATCH, DELETE | project_trigger_repositories_api.py:81,154,205 | can_admin_dataset | admin (PATCH is used by Dagster too, which is fine: system includes admin) |
| `.../pull_requests` GET list, GET one | project_trigger_repositories_api.py:238,278 | can_admin_dataset | user * |
| GET `/projects/<p>/results` list, GET `/<id>` | results_api.py:47,70 | admin_dataset / exec_task | user * |
| GET `/projects/<p>/tasks`, GET `/<id>` | tasks_api.py:86,122 | can_admin_task / exec_task | user * |
| POST `/projects/<p>/tasks`, POST `/validate` | tasks_api.py:228,283 | can_exec_task | user |
| GET `/<id>/trigger`, `/results`, `/logs` | tasks_api.py:300,315,328 | can_exec_task | user |
| POST `/<id>/retry`, `/cancel`, `/results/approve`, `/results/block` | tasks_api.py:193,217,338,350 | can_admin_task | admin (Q1) |

**Wrong-role count (handlers):** 0 unauthenticated by mistake.
- 6 Dagster-only writes open to admins.
- 4 sensor routes (system per the agreed list, today admin).
- 2 `/global/datasets` GETs too loose.
- 2 admin routes outside `/global`.
- 12 project reads gated at admin, too strict for `user` (harmless in an admin-only beta): `GET /projects` and `/<id>`, project datasets (2), project results repos (2), project trigger assignments (2), PR reads (2), results list, tasks list.
- Total: 26.

## 5. Implementation steps

1. **`helpers/wrappers.py`**: add `role` to `auth`.
   - Missing token gives 401. Decode once, then compute the level from `realm_access.roles` (user < admin < system).
   - Too low gives `UnauthorizedError` (403).
   - Set `g.caller_is_admin` and `g.caller_roles`. Remove the DAR TODO block if desired.
   - Keep the `scope=` path until step 3 is done.
2. **`helpers/keycloak.py`**: add `get_roles(token_info)` (or reuse `decode_token`). Delete the System bypass (line 398) and `is_system_user` once `scope=` is gone. Update `is_user_admin` to include Super Administrator and System, or drop it.
3. **Routes**: apply section 4.
   - Hooks: `/global/*` blueprints get `role="admin"`, `/dagster` gets `role="system"`.
   - Add `@auth(role="system")` on the 6 inter-service routes.
   - Replace per-route `scope=` everywhere. Remove the doubled hook and decorator on the same route.
   - Replace `tasks_api.py:56-70` with plain role checks (Q7).
4. **admin_api.py**: optionally move to `/global/audit` and `/global/delivery-secret` (Q5). Update `static/openapi.json` and fncli/Dagster callers.
5. **users_api / keycloak.py:757**: accept `role` in the body, mapped to `Users` / `Administrator` (Q6).
6. **kc-init / realm**: none for the code approach. Only if Keycloak-side policy is wanted: m003 with a `system-only` scope, `system-policy` on every admin scope, and `System` composite of `Administrator`.
7. **Credentials**: none. Dagster and fncli use `dagster-keycloak-creds`, which is the System user. Check after the change that the `dagster` user's token carries `System` in `realm_access.roles` (live check on the dev cluster). Test Dagster sensors and fncli end to end (`make` targets in the Tiltfile flow).
8. **Tests** (`tests/test_auth_roles.py` plus `conftest.py:664-710`):
   - Extend the autouse mock: `decode_token` returns `realm_access.roles` by token string (`user_token`, `admin_token`, `system_token`). Add `system_token` header fixtures.
   - Keep one table `ROUTES = [(method, path, role)]` copied from section 4.
   - A drift test compares `app.url_map` to the table, so a new route fails until it is classified (public routes are listed separately).
   - Per route group, one case per role: no token gives 401; a lower role gives 403; the right role and any higher role are not 401/403 (404 for unknown ids is fine).
   - A few real 2xx cases per group: users list, projects GET, task PATCH, batch ingest.
   - Add a test that `g.caller_is_admin` is true for admin and system.
9. **Docs**: `project/decisions/` ADR for the role model (extends the auth notes in 0017).

## 6. Out of scope

- Project isolation, per-user task ownership (G8 is removed or left as is, see Q7).
- Data access requests (DAR), per-DAR Keycloak clients, token exchange, `can_transfer_token`.
- Fine-grained permissions, per-dataset Keycloak resources and policies.
- Re-attaching `dar_api` and `whitelisted_images_api`.
- Realm cleanup of unused scopes and policies, and the Keycloak-side `System` composite.
- Token caching and perf work beyond reusing the decoded token.

## 7. Open questions

1. Project config writes: should create, patch and delete of projects, assignments and project secrets, plus retry, cancel, approve and block, be `user` or `admin`? Default in the table: `admin`. Your wording "any project's endpoints" could mean all of them are `user`.
2. Sensors: system only (as in your list), or admin too? Operators may want to pause sensors by hand.
3. Should a human admin (or Super Administrator) be able to call system routes for debugging? Default: no. The beta's admin-only users then cannot PATCH tasks or ingest PRs by hand.
4. Does the user role need `GET /global/datasets` to pick a dataset when creating a task? Default: admin only, per "all `/global` is admin".
5. Move `/audit` and `/delivery-secret` under `/global`? It breaks the URL for any caller.
6. `POST /global/users`: require `role` in the body, or default new users to `Administrator` for the admin-only beta?
7. Drop the task owner-or-admin check (`tasks_api.py:56-70`)? It is per-user isolation.
8. Delete the old scopes and policies from `realms.json` later, or leave them as dead config?
9. Is a public `/docs` fine?

## 8. Size

**Small to medium**: about 1 to 2 days. About 40 route edits, one decorator change, one test file, a conftest mock change, no realm migration. Main risk: the large existing test suite relies on the scope-based mock and user-token headers, so route moves will churn many tests.

## Decisions

1. (2026-10-17) Project setup is **admin** for the beta: create/patch/delete projects, project resources and project secrets, and task retry/cancel/approve/block. **user** can read projects and run/read tasks only.
2. (2026-10-17) The six Dagster write routes (PR batch ingest, PR PATCH, PR→task POST, task PATCH, result POST, result PATCH) are **system** only. Humans use retry/cancel/approve/block.
3. (2026-10-17) `/dagster/sensors` (list, get, start/stop) is **admin** (system included by nesting).
4. (2026-10-17) Remove the per-user task owner check in `tasks_api.py`: any user can see any task. Ownership and project isolation are a future ticket.
