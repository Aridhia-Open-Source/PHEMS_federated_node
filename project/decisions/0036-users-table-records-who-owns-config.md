# 0036. A users table records who owns node config

Status: Proposed, 2026-11-17.

## Context

- **Keycloak is the authority for access.** It holds the users, their realm roles (SuperUser, Administrator, Service, Dagster, Users) and the scopes a route requires ([0017](0017-authorization-detached-from-dar-and-keycloak.md)). nexus-api checks a token on each call and keeps nothing about the caller.
- **The legacy `develop` backend kept Keycloak user ids as plain strings,** on the record that needed one (`requests.requested_by`, `audit.requested_by`). There was no users table: nothing to join to, no username, and no foreign key to say the id is real.
- **Config records carry no owner.** Git providers, secrets, trigger and results repositories, datasets, projects and the project's assignments do not say who is responsible for them, so the API and the UI cannot show it.
- **Some config is managed by a program, not a person.** A service account creates records and expects them to stay as it set them; an edit by someone else is drift it has to fight. An operator applying node config from files ([0032](0032-declarative-node-config-through-an-operator.md)) is one such case. Today any admin can change any record.

## Decision

### The users table

- **nexus-api has a `users` table,** one row per Keycloak identity that has called it. It records identity only; access stays in Keycloak.
- **Columns:** `id` (the Keycloak user id, the primary key), `username`, `created_at`, `last_seen_at`.
- **The caller's roles are read from the token** (`realm_access.roles`). `Caller.role` is its node role (below).
- **The row is upserted on each authenticated call.** `get_caller` upserts it (one `INSERT ... ON CONFLICT DO UPDATE`, committed at once), refreshing `username` and `last_seen_at`; a row seen in the last minute under the same username is left alone. The caller then carries `user`.
- **The row is never deleted.** Records keep pointing at it after the Keycloak user is gone.

### Who owns a record

- **Every caller has one node role,** a Keycloak realm role. From most access to least:

  | Role | Held by | Records it creates | May change |
  |---|---|---|---|
  | `SuperUser` | the break-glass account | owned by `SuperUser` | any record, and release any record |
  | `Administrator` | admins, the first user included | owned by `Administrator` | `Administrator` records and open records |
  | `Service` | the nexus operator | owned by `Service` | `Service` records and open records |
  | `Dagster` | the Dagster user | none (it writes pipeline state only) | pull requests, tasks, results, git tokens |
  | `Users` | normal users | open | nothing (read only) |

  The list and its order are fixed in code, not chart values. Each account holds exactly one of these roles: the operator holds only `Service` and the superuser only `SuperUser`, and both get the write scope an Administrator has.
- **Who may change a record lives in one table, `record_access`:**

  ```
  record_access
    id           serial pk
    record_type  text       -- 'project', 'dataset', 'trigger_repository', ...
    record_id    int
    role         text null  -- a node role
    user_id      text null  -- fk users.id (later)
    group_path   text null  -- a Keycloak group (later)
    access       text       -- 'owner' | 'edit'
    created_at   timestamptz
    created_by   text       -- fk users.id
    unique (record_type, record_id, role, user_id, group_path)
    check exactly one of role / user_id / group_path is set
  ```

  Today only `role` rows with `access = 'owner'` are written. `user_id` and `group_path` rows (users owning projects, project members, per-group access) are added later without changing the check. Owned records keep `owner_id` (a foreign key to `users`, who owns it) from one mixin, `OwnedMixin`; a model opts in by inheriting it. Today the owned records are git providers, secrets, trigger and results repositories, datasets, projects, and the project's dataset, secret, trigger repository and results repository assignments.
- **The caller that creates a record owns it** (`set_owner`): `owner_id` is the caller, and one `owner` row is written for its node role. `Users` writes no row, which leaves the record open.
- **The check, on every write** (`get_for_write`):

  ```
  rows = record_access for this record
  if no rows:                             allow   (open record)
  if caller is SuperUser:                 allow
  if any row matches the caller:          allow   (row.role in caller.roles;
                                                   later row.user_id / row.group_path)
  else:                                   409 naming the owner
  ```

- **A caller that writes an open record takes it over:** `owner_id` becomes the caller and an `owner` row is written for its role.
- **Responses show the owner,** as `owner` (`id` and `username`, or null) and `owner_role` (the role of its `owner` row, or null).
- **No groups or per-user access yet.** The table has the columns; nothing writes them until that is built.
- **There is no audit trail yet.** Who changed what, and when, comes later and builds on this table.

### The superuser releases a record

- **The superuser is a break-glass account,** for when an owned record has to change and the service that owns it cannot do it (it is gone, broken, or wrong). It is a Keycloak user with the `SuperUser` realm role only, which has the write scope an Administrator has. The records it creates are owned by `SuperUser`, like any role's.
- **It is set up like the first user.** The chart value `superuserSecret` names a Secret and the keys of its username and password; kc-init creates the account with both roles on every install and upgrade, create-only, so a password changed in Keycloak is kept. In dev, set it in `.dev.env` (`mise run configure` creates the file; left empty, no superuser is made) and `deploy.sh` writes it into the `keycloak-superuser` Secret.
- **Each owned record has a release route,** `POST <record path>/release` (for example `POST /global/datasets/{id}/release`, `POST /projects/{id}/secrets/{label}/release`). It deletes the record's `owner` rows and leaves `owner_id` alone; the record is then open, and changes like any other. Only a caller with the `SuperUser` role may call it (`superuser_only` in `app/helpers/wrappers.py`); an Administrator without it gets a 403.
- **Release is the only override.** The superuser changes nothing else through it: to change the record, it (or anyone) uses the normal routes once the record is open. A service that writes the record again takes it back, as for any open record.

### The check is an explicit loader

- **Every write route loads its record through `get_for_write(session, model, ident, caller, fields=None)`** (`app/helpers/ownership.py`). It finds the record by primary key or by columns (404 if missing, or None for a PUT that creates it), refuses with a 409 when the record is locked to a group the caller is not in, and lets an owner-group member take the record over. Reads keep the normal lookups.
- **A project's owner role also controls what is assigned to it.** Adding, changing or removing a project's datasets, secrets, trigger repositories or results repository is a 409 when the project is owned by a role the caller does not hold (`require_member(project, caller)`). The caller does not take the project over.
- **Cascading deletes follow the same rule.** A forced delete of a global resource, a secret's delete and a project's delete check every project resource they would delete (`require_members`); if any is owned by a role the caller does not hold, the delete is a 409 naming them and nothing is deleted.
- **`fields` narrows the lock later.** A route passes the fields it changes; a model lists the fields its owner role locks in `owner_locked_fields`. Both are unset today, so the whole record is locked.
- **A test lists every POST, PUT, PATCH and DELETE route** as owned, create (no owner to check yet) or unowned. It checks each owned one answers a 409 for a record owned by another group and leaves the record unchanged, and each release route a 403 for anyone but the superuser. A new write route fails it until it is classed, and an owned one until it uses the loader.

### The pattern for nexus-owned tables

- **A table nexus-api owns** is a model in `app/models/`, registered in `app.models`, and created in the single baseline migration ([0023](0023-fastapi-replaces-flask.md)). Keycloak data is copied in only as far as a record needs to refer to it.

## Consequences

- Every config record created from now on says who owns it, and the UI can show it.
- The operator's records cannot drift through the UI or another client; a person who needs to change one does it through the operator's source, or the superuser releases it.
- The operator cannot overwrite what admins create by hand, and admins cannot overwrite what the operator manages. A user's record is open: an admin may change it.
- Each authenticated call writes one row. That is one small upsert on a primary key.
- An admin cannot revoke or delete a record owned by `Service`. Withdrawing it goes through the service, or through the superuser releasing it first.
- The superuser's password is a standing credential that can open any owned record. Its Secret needs the same care as the first user's.
- A service taking a record over replaces the person who owned it; who owned it before is not kept until there is an audit trail.
- Records made before this change, and records made by internal paths with no caller, have no owner and are open.
- Internal updates made without the loader are not checked (skip_gap, disabling what uses a disabled secret).

## Alternatives considered

- **Plain Keycloak id strings, as in `develop`:** no username without a Keycloak call per record and no foreign key.
- **Reading the user from Keycloak on demand:** a Keycloak admin call per record shown, and a deleted Keycloak user leaves the id unreadable.
- **Ownership in Keycloak (a resource per record):** access stays in Keycloak, but a record's owner is a fact about the record, and nexus-api already owns the record and its rules ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)).
- **Locking records a person owns too:** a person's records would then be locked to that person, which is not wanted; only programs need protection from drift.
- **A Super Administrator bypass in `get_for_write`:** every write route would then be an override, and nothing would say a record was opened on purpose. A separate release route is one explicit step, and the realm role keeps it off ordinary admin accounts.
- **Owner groups separate from roles (a configured `ownerGroups` list):** a caller could hold several groups, so a "first one wins" rule was needed, and the group said the same thing as the role. The owner is the creator's role instead.
- **An `owner_role` column on each record:** less work today, but per-user and per-project access would then need the table anyway, touching every owned record, the API responses and the UI a second time. The table costs one lookup per write and has no foreign key to each record type.
- **Locking to the owning user rather than a role:** a second instance of the same service, or a rotated service account, could not change its own records.
- **A SQLAlchemy `before_flush` hook that refuses changes to locked records:** it is implicit, so a reader of a route cannot see the check; it runs where there is no request and no caller (Dagster's state writes, migrations, scripts); it fires on cascades a route makes on purpose; and bulk `query.update()` bypasses it anyway. An explicit loader is visible in each route and the route test covers it.
- **A separate `created_by` next to the owner:** it duplicates the owner until a service takes over, and the history it would keep belongs to the audit trail.

## Open questions

- Which fields are owner-controlled: today any change is refused; `owner_locked_fields` and `fields` are there for when that narrows.
- Per-user and per-project access (users owning projects, specific users editing specific projects): `user_id` and `group_path` rows in `record_access`, and who may grant them.
- Renaming the `Dagster` role to something not tied to Dagster (`Pipeline`) if the orchestrator ever changes.
