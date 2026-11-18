# 0036. A users table records who owns node config

Status: Proposed, 2026-11-17.

## Context

- **Keycloak is the authority for access.** It holds the users, their realm roles (Administrator, Users, System) and the scopes a route requires ([0017](0017-authorization-detached-from-dar-and-keycloak.md)). nexus-api checks a token on each call and keeps nothing about the caller.
- **The legacy `develop` backend kept Keycloak user ids as plain strings,** on the record that needed one (`requests.requested_by`, `audit.requested_by`). There was no users table: nothing to join to, no username, and no foreign key to say the id is real.
- **Config records carry no owner.** Git providers, secrets, trigger and results repositories, datasets, projects and the project's assignments do not say who is responsible for them, so the API and the UI cannot show it.
- **Some config is managed by a program, not a person.** A service account creates records and expects them to stay as it set them; an edit by someone else is drift it has to fight. An operator applying node config from files ([0032](0032-declarative-node-config-through-an-operator.md)) is one such case. Today any admin can change any record.

## Decision

### The users table

- **nexus-api has a `users` table,** one row per Keycloak identity that has called it. It records identity only; access stays in Keycloak.
- **Columns:** `id` (the Keycloak user id, the primary key), `username`, `created_at`, `last_seen_at`.
- **The caller's groups are read from the token:** its realm roles and, when the token has a `groups` claim, its Keycloak groups. `Caller.groups` holds them.
- **Owner groups are one setting,** `OWNER_GROUPS`: a comma-separated list of group or role names, by default `service-account`, set from the chart value `nexus.api.ownerGroups`. That realm role is defined in the chart's realm (`k8s/federated-node/scripts/realms.json`) and granted in Keycloak like any other role.
- **The row is upserted on each authenticated call.** `get_caller` upserts it (one `INSERT ... ON CONFLICT DO UPDATE`, committed at once), refreshing `username` and `last_seen_at`; a row seen in the last minute under the same username is left alone. The caller then carries `user`.
- **The row is never deleted.** Records keep pointing at it after the Keycloak user is gone.

### Who owns a record

- **Owned records carry `owner_id` and `owner_group`,** both nullable, from one mixin, `OwnedMixin`; a model opts in by inheriting it. `owner_id` is a foreign key to `users`; `owner_group` is a group or role name. Today the owned records are git providers, secrets, trigger and results repositories, datasets, projects, and the project's dataset, secret, trigger repository and results repository assignments.
- **The caller that creates a record owns it** (`set_owner`). When the caller is in an owner group, `owner_group` is set to that group and the record is locked to it; otherwise `owner_group` stays null and the record is open.
- **Only members of a record's owner group may change it.** Anyone else (an update, a re-assignment, a delete, a revoke) gets a 409 naming the group. An open record can be changed by anyone the route's scope allows, as before.
- **No admin override.** An Administrator (or Super Administrator) outside the owner group gets the same 409; `get_for_write` has no admin bypass. A record owned by a group changes only through that group, by changing the service's source, or after the superuser releases it (below).
- **A member of an owner group that writes a record takes it over:** `owner_id` becomes the caller, and an open record is locked to the caller's group.
- **Responses show the owner,** as `owner` (`id` and `username`, or null) and `owner_group`.
- **There is no audit trail yet.** Who changed what, and when, comes later and builds on this table.

### The superuser releases a record

- **The superuser is a break-glass account,** for when a record owned by a group has to change and the service that owns it cannot do it (it is gone, broken, or wrong). It is a Keycloak user with the `superuser` realm role, defined in the chart's realm next to `service-account`, and with Administrator for the routes' scope.
- **It is set up like the first user.** The chart value `superuserSecret` names a Secret and the keys of its username and password; kc-init creates the account with both roles on every install and upgrade, create-only, so a password changed in Keycloak is kept. In dev, `mise run init-conf` asks for it and `deploy.sh` writes it into the `keycloak-superuser` Secret.
- **Each owned record has a release route,** `POST <record path>/release` (for example `POST /global/datasets/{id}/release`, `POST /projects/{id}/secrets/{label}/release`). It sets `owner_group` to null and leaves `owner_id` alone; the record is then open, and changes like any other. Only a caller with the `superuser` role may call it (`superuser_only` in `app/helpers/wrappers.py`); an Administrator without it gets a 403.
- **Release is the only override.** The superuser changes nothing else through it: to change the record, it (or anyone) uses the normal routes once the record is open. A service that writes the record again takes it back, as for any open record.

### The check is an explicit loader

- **Every write route loads its record through `get_for_write(session, model, ident, caller, fields=None)`** (`app/helpers/ownership.py`). It finds the record by primary key or by columns (404 if missing, or None for a PUT that creates it), refuses with a 409 when the record is locked to a group the caller is not in, and lets an owner-group member take the record over. Reads keep the normal lookups.
- **A project's owner group also controls what is assigned to it.** Adding, changing or removing a project's datasets, secrets, trigger repositories or results repository is a 409 when the project is owned by a group the caller is not in (`require_member(project, caller)`). The caller does not take the project over.
- **Cascading deletes follow the same rule.** A forced delete of a global resource, a secret's delete and a project's delete check every project resource they would delete (`require_members`); if any is owned by a group the caller is not in, the delete is a 409 naming them and nothing is deleted.
- **`fields` narrows the lock later.** A route passes the fields it changes; a model lists the fields its owner group locks in `owner_locked_fields`. Both are unset today, so the whole record is locked.
- **A test lists every POST, PUT, PATCH and DELETE route** as owned, create (no owner to check yet) or unowned. It checks each owned one answers a 409 for a record owned by another group and leaves the record unchanged, and each release route a 403 for anyone but the superuser. A new write route fails it until it is classed, and an owned one until it uses the loader.

### The pattern for nexus-owned tables

- **A table nexus-api owns** is a model in `app/models/`, registered in `app.models`, and created in the single baseline migration ([0023](0023-fastapi-replaces-flask.md)). Keycloak data is copied in only as far as a record needs to refer to it.

## Consequences

- Every config record created from now on says who owns it, and the UI can show it.
- A service account's records cannot drift through the UI or another client; a person who needs to change one does it through the service's source, or is added to the owner group.
- Each authenticated call writes one row. That is one small upsert on a primary key.
- An admin outside the owner group cannot revoke or delete a record owned by a group. Withdrawing it goes through the service, or through the superuser releasing it first.
- The superuser's password is a standing credential that can open any record owned by a group. Its Secret needs the same care as the first user's.
- A service taking a record over replaces the person who owned it; who owned it before is not kept until there is an audit trail.
- Records made before this change, and records made by internal paths with no caller, have no owner and are open.
- Internal updates made without the loader are not checked (skip_gap, disabling what uses a disabled secret).

## Alternatives considered

- **Plain Keycloak id strings, as in `develop`:** no username without a Keycloak call per record and no foreign key.
- **Reading the user from Keycloak on demand:** a Keycloak admin call per record shown, and a deleted Keycloak user leaves the id unreadable.
- **Ownership in Keycloak (a resource per record):** access stays in Keycloak, but a record's owner is a fact about the record, and nexus-api already owns the record and its rules ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)).
- **Locking records a person owns too:** a person's records would then be locked to that person, which is not wanted; only programs need protection from drift.
- **A Super Administrator bypass in `get_for_write`:** every write route would then be an override, and nothing would say a record was opened on purpose. A separate release route is one explicit step, and the realm role keeps it off ordinary admin accounts.
- **Locking to the owning user rather than a group:** a second instance of the same service, or a rotated service account, could not change its own records.
- **A SQLAlchemy `before_flush` hook that refuses changes to locked records:** it is implicit, so a reader of a route cannot see the check; it runs where there is no request and no caller (Dagster's state writes, migrations, scripts); it fires on cascades a route makes on purpose; and bulk `query.update()` bypasses it anyway. An explicit loader is visible in each route and the route test covers it.
- **A separate `created_by` next to the owner:** it duplicates the owner until a service takes over, and the history it would keep belongs to the audit trail.

## Open questions

- Which fields are owner-controlled: today any change is refused; `owner_locked_fields` and `fields` are there for when that narrows.
- Whether the Dagster System user should be in an owner group. It holds `System`, not `service-account`, so its writes lock nothing; it creates no config records.
