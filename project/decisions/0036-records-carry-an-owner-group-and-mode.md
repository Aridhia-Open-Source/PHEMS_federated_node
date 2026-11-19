# 0036. Records carry an owner, a group and a mode

Status: Proposed, 2026-11-19.

## Context

- **Keycloak is the authority for identity.** It holds the users, their realm roles and groups, and the scopes a route requires ([0017](0017-authorization-detached-from-dar-and-keycloak.md)). nexus-api checks a token on each call.
- **The legacy `develop` backend kept Keycloak user ids as plain strings,** on the record that needed one (`requests.requested_by`, `audit.requested_by`). There was no users table: nothing to join to, no username, and no foreign key to say the id is real.
- **Config records carry no owner.** Git providers, secrets, trigger and results repositories, datasets, projects and the project's assignments do not say who made them or who may change them, so the API and the UI cannot show it.
- **Some config is managed by a program, not a person.** A service account creates records and expects them to stay as it set them; an edit by someone else is drift it has to fight. An operator applying node config from files ([0032](0032-declarative-node-config-through-an-operator.md)) is one such case. Today any admin can change any record.
- **Who may run a task on what is coming.** The task API trigger is coming back, and a task will need a rule for which projects and datasets it may use.
- **A record's rules belong to nexus-api** ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)): who owns a record is a fact about the record, not about the caller.

## Decision

Records are owned the way Unix files are: an owner, a group and a mode (`rwx` for owner, group and others). Keycloak says who the caller is and what scopes it has; nexus-api says what the caller may do to each record.

### The users table

- **nexus-api has a `users` table,** one row per Keycloak identity that has called it. It records identity only.
- **Columns:** `id` (the Keycloak user id, the primary key), `username`, `created_at`, `last_seen_at`.
- **The row is upserted on each authenticated call.** `get_caller` upserts it (one `INSERT ... ON CONFLICT DO UPDATE`, committed at once), refreshing `username` and `last_seen_at`; a row seen in the last minute under the same username is left alone. The caller then carries `user`.
- **The row is never deleted.** Records keep pointing at it after the Keycloak user is gone.

### The principals table

- **A principal is a realm role or a Keycloak group** that can own a record or be its group:

  ```
  principals
    id    serial pk
    kind  text   -- 'role' | 'group'
    name  text   -- 'Administrator', '/projects/uc1'
    unique (kind, name)
  ```

- **Principals are upserted from the token on each call,** like users and with the same one-minute skip: the caller's realm roles (`realm_access.roles`) and groups (`groups`). Keycloak's built-in roles (`offline_access`, `default-roles-*`) are ignored.
- **The realm has a groups mapper,** so tokens carry the caller's groups.
- **The model is `app/models/principal.py`,** created in the single baseline migration like `users` ([0023](0023-fastapi-replaces-flask.md)).

### Roles and scopes

- **Each account holds one node role,** a realm role. From most access to least:

  | Role | Held by |
  |---|---|
  | `SuperUser` | the break-glass account, like root |
  | `Administrator` | admins, the first user included |
  | `Service` | the nexus operator; equal to `Administrator` |
  | `Users` | normal users |

  `Dagster` (now `System`, renamed in a separate change) writes pipeline state only and owns no config. The list and its order are fixed in code, not chart values. The operator holds only `Service` and the superuser only `SuperUser`.
- **Scopes say what kind of record a caller may write.** `can_do_admin` splits into:
  - `global:write`: git providers, secrets, trigger and results repositories, datasets.
  - `project:write`: projects and their assignments.

  `SuperUser`, `Administrator` and `Service` hold both today. Users and project groups get `project:write` later.
- **Keycloak gives identity and coarse scopes; nexus-api gives the per-record rules.** Keycloak Authorization Services are not used.

### Every owned record has an owner, a group and a mode

- **`OwnedMixin` adds four columns** to every owned record (git providers, secrets, trigger and results repositories, datasets, projects, and the project's dataset, secret, trigger repository and results repository assignments):

  ```
  created_by  text  fk users.id       -- who made it
  owner_id    int   fk principals.id  -- the creator's node role; null = open
  group_id    int   fk principals.id  -- null = no group
  mode        int   default 0o770     -- rwx for owner / group / others
  ```

  Records point at principals and users; nothing points back.
- **The default mode is one constant,** `DEFAULT_MODE = 0o770` in nexus-api, like a umask, and is the column default. A chart value only comes if a site needs another.
- **The mode is stored as an int and shown as Unix text.** The API and UI show and accept `rwxrwx---` (owner, group, others; `r`, `w`, `x`).
- **The bits mean:**
  - `r`: read. Not enforced yet; reads stay open.
  - `w`: change or delete the record.
  - `x`: run tasks with it. A task needs `x` on both its project and its dataset. Enforced when the task API trigger returns.
- **The creator's role owns a record.** On create, `created_by` is the caller, `owner_id` its node role, `group_id` null and `mode` the default.
- **Edits never change the owner.** Writing a record does not take it over; only the claim route below does.
- **One group per record.** Several groups with different rights need access lists (ACLs), as Unix added later.

### The check on every write

- **The scope first, then the record.** A route requires its scope; then `get_for_write` checks the record:

  ```
  if caller is SuperUser:                          allow
  if record has no owner:                          allow   (open record)
  if caller holds the owner role and owner has w:  allow
  if caller is in the group and group has w:       allow
  if others have w:                                allow
  else:                                            409 naming the owner
  ```

- **Every write route loads its record through `get_for_write(session, model, ident, caller, fields=None)`** (`app/helpers/ownership.py`). It finds the record by primary key or by columns (404 if missing, or None for a PUT that creates it) and applies the check. Reads keep the normal lookups.
- **A project's rights cover what is assigned to it.** Adding, changing or removing a project's datasets, secrets, trigger repositories or results repository needs `w` on the project (`require_member(project, caller)`).
- **Cascading deletes follow the same rule.** A forced delete of a global resource, a secret's delete and a project's delete check every project resource they would delete (`require_members`); if the caller lacks `w` on any of them, the delete is a 409 naming them and nothing is deleted.
- **`fields` narrows the check later.** A route passes the fields it changes; a model lists the fields its owner locks in `owner_locked_fields`. Both are unset today, so the whole record is checked.
- **A test lists every POST, PUT, PATCH and DELETE route** as owned, create (no record to check yet) or unowned. It checks each owned one answers a 409 to a caller without `w` and leaves the record unchanged. A new write route fails it until it is classed, and an owned one until it uses the loader.
- **Responses show the owner,** as `created_by` (`id` and `username`), `owner` and `group` (principal names, or null) and `mode` (`rwxrwx---`).

### Claiming a record

- **`PUT <record path>/owner`, with no body, makes the caller's node role the owner.** For example `PUT /global/datasets/{id}/owner`. It replaces the release route.
- **Only a higher role may claim.** `SuperUser` may claim any record. `Administrator` and `Service` are equal, so neither claims the other's records; both may claim records owned by `Users`. Anything else is a 403.
- **The superuser is the break-glass account,** for when an owned record has to change and the service that owns it cannot do it (it is gone, broken, or wrong). The chart value `superuserSecret` names a Secret and the keys of its username and password; kc-init creates the account with only the `SuperUser` role on every install and upgrade, create-only, so a password changed in Keycloak is kept. In dev, set it in `.dev.env` (left empty, no superuser is made) and `deploy.sh` writes it into the `keycloak-superuser` Secret.
- **The same route takes a body later,** to hand a record to another role or group. Routes to set the group and the mode come later too.

### The pattern for nexus-owned tables

- **A table nexus-api owns** is a model in `app/models/`, registered in `app.models`, and created in the single baseline migration ([0023](0023-fastapi-replaces-flask.md)). Keycloak data is copied in only as far as a record needs to refer to it.

## Consequences

- Every config record created from now on says who made it, which role owns it and who may change it, and the UI can show it.
- The operator's records cannot drift through the UI or another client: an admin is not the owner and, with the default mode, not in the group or others with `w`. A person who needs to change one does it through the operator's source, or the superuser claims it.
- The operator cannot overwrite what admins create by hand, and admins cannot overwrite what the operator manages.
- Groups and project access come from Keycloak groups without a new table: a record gets a `group_id`.
- Running tasks has a rule (`x`) before the task API trigger needs it.
- Each authenticated call can write a user row and a few principal rows. They are small upserts, skipped when seen in the last minute.
- An admin cannot revoke or delete a record owned by `Service`. Withdrawing it goes through the service, or through the superuser claiming it first.
- The superuser's password is a standing credential that can change any record. Its Secret needs the same care as the first user's.
- Records made before this change, and records made by internal paths with no caller, have no owner and are open.
- Internal updates made without the loader are not checked (skip_gap, disabling what uses a disabled secret).
- The owner-group pieces go: `owner_group`, `OWNER_GROUPS` and the chart's `ownerGroups`, `owner_group_of`, the `admin` role and the release route.

## Alternatives considered

- **Plain Keycloak id strings, as in `develop`:** no username without a Keycloak call per record and no foreign key.
- **Ownership in Keycloak (Authorization Services, a resource per record):** access stays in Keycloak, but a record's owner is a fact about the record, and nexus-api already owns the record and its rules ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)). Every record change would also need a Keycloak call.
- **Owner groups separate from roles (a configured `ownerGroups` list):** a caller could hold several groups, so a "first one wins" rule was needed, and the group said the same thing as the role. The owner is the creator's role instead.
- **A `record_access` table (one row per role, user or group and its access):** it handles many grantees per record, but costs a lookup per write, has no foreign key to each record type, and is more than one owner and one group need. Access lists come later if one group per record is not enough.
- **An `owner_role` column only:** less work today, but groups, per-project access and task rights would then each add columns and touch every owned record, the API responses and the UI again.
- **Locking to the owning user rather than a role:** a second instance of the same service, or a rotated service account, could not change its own records.
- **A release route that opens a record:** it leaves the record ownerless until someone writes it, and an open record is taken over by whoever writes it next. Claiming makes the new owner explicit.
- **Taking over an open record on write:** the owner would then change as a side effect of an edit. The owner changes only through the claim route.
- **A SQLAlchemy `before_flush` hook that refuses changes:** it is implicit, so a reader of a route cannot see the check; it runs where there is no request and no caller (Dagster's state writes, migrations, scripts); it fires on cascades a route makes on purpose; and bulk `query.update()` bypasses it anyway. An explicit loader is visible in each route and the route test covers it.

## Open questions

- Who may set a record's group and mode, and through which routes.
- Whether `Administrator` and `Service` should ever claim each other's records (today only `SuperUser` can).
- Which fields are owner-controlled: today any change is checked; `owner_locked_fields` and `fields` are there for when that narrows.
- When reads start to check `r`.
