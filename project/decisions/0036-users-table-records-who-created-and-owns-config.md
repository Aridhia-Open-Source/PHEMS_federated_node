# 0036. A users table records who created and who owns node config

Status: Proposed, 2026-11-17.

## Context

- **Keycloak is the authority for access.** It holds the users, their realm roles (Administrator, Users, System) and the scopes a route requires ([0017](0017-authorization-detached-from-dar-and-keycloak.md)). nexus-api checks a token on each call and keeps nothing about the caller.
- **The legacy `develop` backend kept Keycloak user ids as plain strings,** on the record that needed one (`requests.requested_by`, `audit.requested_by`). There was no users table: nothing to join to, no username, and no foreign key to say the id is real.
- **Config records carry no author.** Git providers, secrets, trigger and results repositories, datasets, projects and the project's assignments do not say who created them, so the API and the UI cannot show it and an audit cannot start from it.
- **Some config is managed by a program, not a person.** A service account creates records and expects them to stay as it set them; an edit by someone else is drift it has to fight. An operator applying node config from files ([0032](0032-declarative-node-config-through-an-operator.md)) is one such case. Today any admin can change any record.

## Decision

### The users table

- **nexus-api has a `users` table,** one row per Keycloak identity that has called it. It records identity only; access stays in Keycloak.
- **Columns:** `id` (the Keycloak user id, the primary key), `username`, `kind`, `created_at`, `last_seen_at`.
- **`kind` is `human` or `service`.** It is `service` when the token carries the realm role `service-account`, otherwise `human`. The role is defined in the chart's realm (`k8s/federated-node/scripts/realms.json`) and granted in Keycloak like any other role.
- **The row is written on each authenticated call.** `get_caller` upserts it (one `INSERT ... ON CONFLICT DO UPDATE`, committed at once), refreshing `username`, `kind` and `last_seen_at`. The caller then carries `user` and `kind`.
- **The row is never deleted.** Records keep pointing at it after the Keycloak user is gone.

### Who created and who owns a record

- **Config records get `created_by_id` and `owner_id`,** both nullable foreign keys to `users`: git providers, secrets, trigger and results repositories, datasets, projects, and the project's dataset, trigger repository and results repository assignments. They come from one mixin, `OwnedMixin`.
- **`created_by_id` is set on create,** to the caller.
- **`owner_id` is set on create only when the caller is a service.** A record a person creates has no owner.
- **A record owned by a service is changed only by its owner.** Any change by another caller (an update, a re-assignment, a delete, a revoke) is refused with a 409. The guard is one helper, `refuse_unless_owner(record, caller, fields=None)`, called before the change; `fields` lets a route narrow it to the owner-controlled fields later.
- **Responses show both,** as `created_by` and `owner` (`id` and `username`, or null).

### The pattern for nexus-owned tables

- **A table nexus-api owns** is a model in `app/models/`, registered in `app.models`, and created in the single baseline migration ([0023](0023-fastapi-replaces-flask.md)). Keycloak data is copied in only as far as a record needs to refer to it.

## Consequences

- Every config record created from now on says who created it, and the UI can show it.
- A service account's records cannot drift through the UI or another client; a person who needs to change one does it through the service's source.
- Each authenticated call writes one row. That is one small upsert on a primary key.
- An admin cannot revoke or delete a record a service owns. Withdrawing it goes through the service.
- Records made before this change, and records made by internal paths with no caller, have no creator and no owner.

## Alternatives considered

- **Plain Keycloak id strings, as in `develop`:** no username without a Keycloak call per record, no foreign key, and nowhere to keep the kind.
- **Reading the user from Keycloak on demand:** a Keycloak admin call per record shown, and a deleted Keycloak user leaves the id unreadable.
- **Ownership in Keycloak (a resource per record):** access stays in Keycloak, but a record's owner is a fact about the record, and nexus-api already owns the record and its rules ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)).
- **An owner on every record, people included:** a person's records would then be locked to that person, which is not wanted; only programs need protection from drift.

## Open questions

- Whether an admin should be able to override a service's ownership (for example, to revoke in an emergency) or take a record over.
- Which fields are owner-controlled: today any change is refused; the guard takes a field list for when that narrows.
- Whether a forced delete of a global resource, or a project's delete, should also be refused when it cascades to a project resource a service owns. Today only the record addressed is checked.
- Whether the Dagster System user should be of kind `service`. It holds `System`, not `service-account`, so today it is `human`; it creates no config records.
- An audit trail of changes (who changed what, when) builds on this table and is not part of this record.
