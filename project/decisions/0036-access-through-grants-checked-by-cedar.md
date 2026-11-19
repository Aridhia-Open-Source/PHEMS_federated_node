# 0036. Access through grants, checked by Cedar

Status: Proposed, 2026-11-19.

## Context

- **Keycloak signs people in.** It holds the accounts, their realm roles and groups, and issues the tokens nexus-api checks ([0017](0017-authorization-detached-from-dar-and-keycloak.md)). At a site it can also hand sign-in to the hospital's directory, GitHub or Entra ID.
- **Config records say nothing about access.** Git providers, secrets, trigger and results repositories, datasets, projects and the project's assignments do not say who made them, who owns them or who may change them. Any admin can change any record.
- **Some config is managed by a program.** The operator applies node config from files ([0032](0032-declarative-node-config-through-an-operator.md)); an edit by someone else is drift it has to fight.
- **Projects have members with different rights.** An admin sets up a study: global resources, projects, then users who mostly read, some who write and some who run tasks. People join and leave, and their rights change.
- **Approved data access requests are coming back with the task API trigger.** A data custodian approves a researcher to run tasks on a project until a date, and may revoke it.
- **The legacy `develop` backend kept access in Keycloak Authorization Services** (below).
- **A record's rules belong to nexus-api** ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)).

### Why the legacy design falls short

`develop` stored a Keycloak resource, policy and permission per dataset, a Keycloak client and user per data access request, and checked every call in the `@auth` decorator (`webserver/app/helpers/wrappers.py`):

- **Up to five Keycloak calls per request:** a user lookup, an admin check, a role check, a token exchange and the permission check, plus one more lookup in `@audit`. Keycloak being slow or down stopped every call.
- **The record checked was guessed, not loaded.** The decorator took the dataset from the URL arguments, then replaced it with any `dataset_id` or `dataset_name` found anywhere in the JSON body, nested keys included. `PATCH /datasets/5` with `{"catalogue": {"dataset_id": 7}}` was checked against dataset 7 and edited dataset 5. Only admins and the system account held `can_admin_dataset`, so it gave nobody extra access, but the record checked was not always the record changed. With no dataset found, it checked a generic `endpoints` resource, which was the scope alone.
- **The client chose the access request:** a `project-name` header picked which data access request, and which token exchange, applied.
- **Rules were split and hidden.** Role names hard-coded in the decorator skipped checks; the rest sat in Keycloak configuration that `realms.json` did not fully apply, so nobody could read the rules in one place.
- **Two stores, no transaction.** Creating a dataset made several Keycloak admin calls before the database commit; a failure part way left Keycloak and the database apart. Deleting a dataset never removed its Keycloak resource, and a rename patched one resource per access request in a loop.
- **Only datasets had per-record rules.** Projects, secrets and repositories had none.
- **Revoking lagged** until tokens already issued expired.

This design answers each point:

| Legacy | Here |
|---|---|
| Keycloak calls on every request | none; the token is checked locally and grants are one query |
| record guessed from URL or body | each route loads its record and passes it to `can()` |
| client header picks the access request | the grant names the user; nothing is read from headers |
| rules in code and Keycloak config | one Cedar policy file, validated and tested |
| two stores without a transaction | grants are rows in the record's own transaction |
| datasets only | every owned record type |
| revoke waits for token expiry | deleting a grant applies at once |

## Decision

Keycloak authenticates and gives each account a broad role. nexus-api authorises: a `grants` table says who may do what to each record, and a Cedar policy file says what each grant allows.

### Keycloak: accounts, roles and groups

- **Each account holds one node role,** a realm role, for setup and broad scopes:

  | Role | Held by |
  |---|---|
  | `SuperUser` | the break-glass account; may do anything |
  | `Administrator` | admins, the first user included |
  | `Service` | the nexus operator |
  | `Users` | normal users |
  | `Dagster` | the Dagster account; writes pipeline state only |

  kc-init creates the first admin, the superuser, the Dagster account and the operator account on install, so they work before nexus-api holds any rows. The list is fixed in code.
- **Groups are Keycloak groups** (for example `/studies/uc1`). Admins manage membership in Keycloak; later a hospital's directory groups can feed them. The realm has a groups mapper, so tokens carry the caller's groups.
- **Keycloak holds nothing per record.** Keycloak Authorization Services are not used.

### nexus-api: users, grants and policy versions

- **`users`:** one row per Keycloak account that has called nexus-api (`id` the Keycloak user id, `username`, `created_at`, `last_seen_at`), upserted from the token on each call and skipped when seen in the last minute. Never deleted.
- **`grants`:** who may do what to which record:

  ```
  grants
    id            serial pk
    object_type   text        -- the model's authz_type: 'Project', 'Dataset', ...
    object_id     int
    relation      text        -- 'owner' | 'read' | 'write' | 'execute'
    subject_type  text        -- 'user' | 'group' | 'role'
    subject_id    text        -- Keycloak user id, group path or role name
    expires_at    timestamptz null
    created_by    text        fk users.id
    created_at    timestamptz
    unique (object_type, object_id, relation, subject_type, subject_id)
  ```

  `object_type`, `relation` and `subject_type` are checked against fixed lists. `object_id` has no foreign key, since it points at many tables; deleting a record deletes its grants in the same transaction.
- **Each owned model declares `authz_type`** (`authz_type = "Dataset"`), stored in grants and used in the policies. It is never derived from the class or table name, so renaming either breaks nothing. `OwnedMixin` fails at import if a model leaves it out.
- **`policy_versions`:** the hash and contents of the policy files nexus-api started with, one row per new hash, for audit.
- **Record tables get no new columns.**

### Where grants come from

- **On create,** nexus-api adds an `owner` grant for the creator's node role, in the same transaction as the record.
- **On delete,** the record's grants go too.
- **Through routes on each owned record:**
  - `GET <record path>/grants` lists them;
  - `POST <record path>/grants` adds one (`relation`, `subject_type`, `subject_id`, `expires_at`);
  - `DELETE <record path>/grants/{id}` removes one.

  The record's owner, or `SuperUser`, may add or remove `read`, `write` and `execute` grants.
- **Claiming:** `PUT <record path>/owner`, with no body, replaces the `owner` grant with the caller's node role. Only a higher role may claim: `SuperUser` any record, `Administrator` and `Service` records owned by `Users`.
- **Approving a data access request** adds an `execute` grant with an expiry; revoking deletes it.
- **Nobody writes the table directly.**

### Policies: Cedar files in the repo

- **The rules are Cedar policies** ([cedar-policy/cedar](https://github.com/cedar-policy/cedar)), evaluated in-process by `cedarpy`. Cedar stores nothing; nexus-api passes in what each request needs.
- **Files:** `nexus/api/authz/policies.cedar` (the rules), `schema.cedarschema` (entity types, attributes and actions) and `cases.yaml` (allow and deny cases), committed, reviewed by PR and built into the image.
- **The standard rules:**

  ```
  // Owners may do anything to the record.
  permit (principal, action, resource)
  when { context.grants has owner && context.grants.owner > context.now };

  // read, write and execute grants each allow their own action, until they expire.
  permit (principal, action == Action::"read", resource)
  when { context.grants has read && context.grants.read > context.now };
  permit (principal, action == Action::"write", resource)
  when { context.grants has write && context.grants.write > context.now };
  permit (principal, action == Action::"execute", resource)
  when { context.grants has execute && context.grants.execute > context.now };

  // SuperUser may do anything.
  permit (principal in Role::"SuperUser", action, resource);

  // Nobody runs tasks on a revoked dataset.
  forbid (principal, action == Action::"execute", resource is Dataset)
  when { resource.revoked };
  ```

- **Nothing is allowed unless a `permit` matches,** and a `forbid` always wins.
- **Sites add rules later** as extra `.cedar` files through chart values, versioned in the site's repo ([0031](0031-gitops-delivery-with-helm-and-flux.md)). They add to the standard rules and cannot remove them. A new action needs code, since a route has to ask for it.
- **Tested:** CI validates the policies against the schema and runs `cases.yaml` in pytest. At startup nexus-api validates them again, refuses to start if they fail, and writes a `policy_versions` row if the hash is new.

### The check

- **Every write route calls `can(caller, action, record)`** (`app/helpers/authz.py`); a deny is a 409 naming the owner. It:
  1. reads the caller from the token: user id, node role, groups;
  2. loads the caller's grants on the record (one query on `grants` matching the user, role or groups), as one expiry per relation;
  3. builds the Cedar request: the user with its role and groups as parents, the record, and `context` with the grants and the time;
  4. returns Cedar's decision.
- **A project's rights cover its assignments.** Adding or removing a project's datasets, secrets, trigger repositories or results repository needs `write` on the project and on the global resource.
- **Cascading deletes check every record they would delete;** if the caller may not write one, nothing is deleted.
- **Scopes stay coarse.** A route still requires its token scope first.
- **`execute` is checked for tasks requested through the API.** Tasks started by merged pull requests are not checked, for now:
  - nexus-api cannot tell who raised or merged a pull request until a hospital links GitHub or Azure identities to Keycloak, and most sites have not yet;
  - it is not settled whether the raiser or the merger should need `execute`; if it is the merger, the right to merge already is the permission.

  The trigger repository's permissions and the pull request review are the gate there.
- **A test lists every POST, PUT, PATCH and DELETE route** as owned, create or unowned, and checks each owned route answers a 409 to a caller without the grant and leaves the record unchanged. A new write route fails it until it is classed.

### With Flux and the operator

The site's git repository already drives the node: Flux deploys the chart ([0031](0031-gitops-delivery-with-helm-and-flux.md)) and the operator applies node config through nexus-api ([0032](0032-declarative-node-config-through-an-operator.md)). Access fits the same flow:

- **Policies from git.** A site's extra `.cedar` files are chart values in its Flux repository, changed by PR. Flux rolls them out; nexus-api validates them at startup, so a bad policy fails the rollout and the previous pods keep serving.
- **Config owned by the operator.** The operator calls nexus-api as `Service`, so every record it applies gets an `owner` grant for `Service`. A UI edit by an admin is a 409: the records cannot drift from git. Changing one means a PR to the site repository, or the superuser claiming it when the operator is broken.
- **Standing access from git.** An operator resource can declare who may use it, for example a Project with `access: [{group: uc1-team, relation: read}]`. The operator reconciles that list through the `/grants` routes; the grants it makes are owned through `Service` like the record, and removing a line from git removes the grant.
- **Groups, not users, in git.** Git names groups (`uc1-team`); membership stays in Keycloak or the hospital's directory, so no Keycloak user ids are committed.
- **Decisions on the day stay at runtime.** Approving a data access request, with its expiry, is a grant made through the API, not a PR. Its `created_by` and the audit trail record who approved it.
- **Rules versioned with the node.** `policy_versions` records the hash of the policies each pod started with, so any decision can be traced to the commit that set the rules.

The operator's `access` list is designed when the operator work resumes; nothing here depends on it.

### An example

- Dana (`Administrator`) creates project 3: grant `Project 3, owner, role Administrator`.
- In Keycloak she adds Alice and Bob to group `uc1-team`. In nexus-api she grants `uc1-team` `read`, Alice `write`, and Bob `execute` until 2027-03-01.
- Alice edits project 3: allowed. Bob edits it: denied. Bob runs a task: allowed, until March.
- Dana removes Alice from `uc1-team`: Alice loses `read` when her token next refreshes, and keeps her own `write` grant.

## Consequences

- Every config record created from now on has an owner, and the UI can show who may do what.
- The operator's records cannot drift through the UI: they are owned by `Service`, and only their owner or the superuser may change them or their grants.
- Approving and revoking access is one row in nexus-api's own transaction. Revoking a grant applies at once; removing someone from a Keycloak group applies when their token next refreshes, within minutes.
- Access rules are a readable, standard file, tested in CI and at startup, with each version recorded.
- Each write makes one small query on `grants` and one in-process Cedar call.
- Group membership changes in Keycloak are outside nexus-api's audit trail.
- `cedarpy` is a thin community wrapper over Cedar's Rust core; it is pinned, and forked if it stalls.
- Records made before this change, and by internal paths with no caller, have no grants; only `SuperUser` may change them until someone claims them.
- The owner-group pieces go: `owner_group`, `OWNER_GROUPS` and the chart's `ownerGroups`, `owner_group_of`, the `admin` role and the release route.

## Alternatives considered

- **Keycloak Authorization Services, as in `develop`:** every record change needs several Keycloak admin calls with no shared transaction, so Keycloak and the database drift; revoking lags until tokens expire; tests need a running Keycloak; and a client per access request scales badly.
- **Owner groups from a configured `ownerGroups` list (the previous version of this ADR):** one lock per record, no per-user rights and no expiry.
- **Unix-like owner, group and mode columns on each record:** simple, but one group per record, mode bits that do not map to other engines, and access lists needed as soon as two groups need different rights.
- **Our own rules dict in Python:** less to install, but not a standard format, and sites cannot read or extend it.
- **Casbin (in-process):** maintained, but its generic `casbin_rule` table loses typed columns and audit fields unless we write an adapter, and it keeps every rule in memory, needing a watcher across replicas.
- **OpenFGA (a Zanzibar-style service):** a strong fit for many services or nested sharing, but another service per node and the same two-place problem as Keycloak. Grants map one to one to its tuples, so moving later is open.
- **Open Policy Agent or Cerbos:** standard policy files, but each runs as a sidecar or service, and Rego is hard to read.
- **Cedar policy templates for grants:** Cedar's native way, but a template link cannot carry an expiry, and a plain table is easier to query and report on.

## Open questions

- Who may create groups and grant to them, and whether nexus-api should manage Keycloak group membership through its own routes.
- Whether sites may add `permit` rules or only `forbid` rules.
- When reads start to check `read`.
- The shape of the operator's `access` list, and whether UI grants and git grants may sit on the same record.
