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
| record guessed from URL or body | each route receives its record through its `Access` check |
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
    relation      text        -- 'owner' | 'read' | 'write' | 'execute' | 'assign'
    subject_type  text        -- 'user' | 'group' | 'role'
    subject_id    text        -- Keycloak user id, group path or role name
    expires_at    timestamptz null
    created_by    text        fk users.id
    created_at    timestamptz
    unique (object_type, object_id, relation, subject_type, subject_id)
  ```

  `object_type`, `relation` and `subject_type` are checked against fixed lists. `object_id` has no foreign key, since it points at many tables; deleting a record deletes its grants in the same transaction.
- **Grants sit on projects and global records only.** A project is a set of resources with one set of permissions: its secrets, trigger and results repositories and assignments have no grants of their own, and every check on them is a check on the project. Each of those resources still records `created_by`.
- **Each model with grants declares `authz_type`** (`authz_type = "Dataset"`), stored in grants and used in the policies. It is never derived from the class or table name, so renaming either breaks nothing. `OwnedMixin` fails at import if a model leaves it out.
- **`policy_versions`:** the hash and contents of the policy files nexus-api started with, one row per new hash, for audit.
- **Record tables get no new columns.**

### Where grants come from

- **What each relation allows:**

  | Relation | Allows |
  |---|---|
  | `owner` | everything, including managing the record's grants |
  | `write` | change or delete it; read it |
  | `execute` | run tasks with it; read it |
  | `assign` | add it to a project (a project assignment) without changing it; read it |
  | `read` | read it |

  Every action, reads included, is checked.
- **People own what they create.** On creating a project or a global record, nexus-api adds an `owner` grant for the creating user, in the same transaction as the record. Records the operator creates are owned by `role:Service` instead, so a rotated or second operator account still owns them.
- **Global records can be assigned by any admin.** Every global record also gets an `assign` grant for `role:Administrator` on create, whoever made it, so any admin can add it to their projects without being able to change it. Its owner can remove that grant, for example from a sensitive dataset, and grant `assign` to chosen admins or groups instead.
- **`Global` is the container for global records,** as a project is for project records. Creating a global record (a dataset, git provider, secret, trigger or results repository, or a project) needs `write` on `Global`. The baseline migration gives `role:Administrator` and `role:Service` `owner` on `Global`, so any admin or the operator can create them; a `write` grant on `Global` scopes that to another group later. `Global` is not a table: its grants use `object_type = 'Global'`, `object_id = 0`.
- **On delete,** the record's grants go too.
- **Through routes on each project and global record:**
  - `GET <record path>/grants` lists them;
  - `POST <record path>/grants` adds one (`relation`, `subject_type`, `subject_id`, `expires_at`);
  - `DELETE <record path>/grants/{id}` removes one.

  Only the record's owner, or `SuperUser`, may add or remove its grants. Assigning users and groups to a project is the owning admin's job; a user with `write` cannot grant access to others.
- **Claiming:** `PUT <record path>/owner`, with no body, makes the caller the owner. Only `SuperUser` may claim, for example when the owning admin has left. Handing a record to a named user or group (the same route with a body) comes later.
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

  // write, execute and assign each allow their own action, until they expire.
  permit (principal, action == Action::"write", resource)
  when { context.grants has write && context.grants.write > context.now };
  permit (principal, action == Action::"execute", resource)
  when { context.grants has execute && context.grants.execute > context.now };
  permit (principal, action == Action::"assign", resource)
  when { context.grants has assign && context.grants.assign > context.now };

  // Any current grant lets you read the record.
  permit (principal, action == Action::"read", resource)
  when {
    (context.grants has read && context.grants.read > context.now) ||
    (context.grants has write && context.grants.write > context.now) ||
    (context.grants has execute && context.grants.execute > context.now) ||
    (context.grants has assign && context.grants.assign > context.now)
  };

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

- **Every write route declares an `Access` dependency** (`app/helpers/authz.py`), with keyword arguments only:

  ```python
  class Action(StrEnum):
      READ = "read"
      WRITE = "write"
      EXECUTE = "execute"
      ASSIGN = "assign"
      UNCHECKED = "unchecked"   # no record check; the route has no record

  @router.patch("/{dataset_id}")
  def patch_dataset(dataset: Dataset = Depends(Access(model=Dataset, action=Action.WRITE))):

  # gets a token; no record yet
  @router.post("/login", dependencies=[Depends(Access(action=Action.UNCHECKED))])
  def login(body: LoginBody):
  ```

  `Access` takes keyword arguments only, and raises at import if `model` is missing for a checked action or given with `Action.UNCHECKED`. Every `Action` except `UNCHECKED` must exist in the Cedar schema, checked at startup. An unchecked route gives its reason in a comment above it.
- **A checked route only receives its record through the check,** so it cannot use one unchecked. A deny is a 409 naming the owner. `Access`:
  1. loads the record from the path (404 if missing);
  2. reads the caller from the token: user id, node role, groups;
  3. loads the caller's grants on the record (one query on `grants` matching the user, role or groups), as one expiry per relation;
  4. builds the Cedar request: the user with its role and groups as parents, the record, and `context` with the grants and the time;
  5. returns the record if Cedar allows, and raises otherwise.

  An unchecked route needs no token from `Access`. Code that is not a route (cascades, the grants routes) calls the same check as `can(caller, action, record)`.
- **Creates check their parent.** A record that does not exist yet is checked through the record it is created under:
  - creates inside a project (a project's secret, trigger repository or results repository) need `write` on the project, and so do changes and deletes of them: `Access(model=Project, action=Action.WRITE)`;
  - global creates (datasets, git providers, secrets, trigger and results repositories, projects) need `write` on `Global`, `Access(model=Global, action=Action.WRITE)`.

  Who may create global records is then a grant and a Cedar rule, as for projects, not only a Keycloak scope.
- **Deny by default, checked at startup.** `create_app` walks every route, reads included, and refuses to start if one has no `Access` dependency, as `OPEN_ROUTERS` does for scopes today. A forgotten check stops nexus-api from starting, so it fails every test run and every deploy, not only one test. Today's unchecked routes are the health checks, login, token refresh, a user's own password reset, and Dagster's pipeline state writes; a snapshot test lists them, so a new one shows up in review.
- **Assigning needs both sides.** Adding or removing a project's datasets, secrets, trigger repositories or results repository needs `write` on the project (through `Access`) and `assign` on the global record (through `can()`).
- **Lists show only what the caller may read.** List routes filter their query by the caller's grants (a join on `grants` for the user, role or groups), then Cedar checks each row; `SuperUser` sees everything.
- **Cascading deletes check every record they would delete;** if the caller may not write one, nothing is deleted.
- **Scopes stay coarse.** A route still requires its token scope first; the record check comes after.
- **`execute` is checked for tasks requested through the API.** Tasks started by merged pull requests are not checked, for now:
  - nexus-api cannot tell who raised or merged a pull request until a hospital links GitHub or Azure identities to Keycloak, and most sites have not yet;
  - it is not settled whether the raiser or the merger should need `execute`; if it is the merger, the right to merge already is the permission.

  The trigger repository's permissions and the pull request review are the gate there.
- **A test walks every checked write route** and checks it answers a 409 to a caller without the grant and leaves the record unchanged.

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

- The operator creates dataset 12: grants `Dataset 12, owner, role Service` and `Dataset 12, assign, role Administrator`.
- Dana (`Administrator`) creates project 3: grant `Project 3, owner, user dana`.
- Dana adds dataset 12 to project 3: allowed (`write` on the project, `assign` on the dataset). She renames dataset 12: denied, it is the operator's.
- In Keycloak she adds Alice and Bob to group `uc1-team`. In nexus-api she grants `uc1-team` `read`, Alice `write`, and Bob `execute` until 2027-03-01.
- Alice edits project 3: allowed. Bob edits it: denied. Bob runs a task: allowed, until March. Alice tries to grant access to someone: denied, only Dana owns it.
- Dana removes Alice from `uc1-team`: Alice keeps her own `write` grant, which also lets her read.

## Consequences

- Every config record created from now on has an owner, and the UI can show who may do what.
- The operator's records cannot drift through the UI: they are owned by `Service`, and only their owner or the superuser may change them or their grants.
- Approving and revoking access is one row in nexus-api's own transaction. Revoking a grant applies at once; removing someone from a Keycloak group applies when their token next refreshes, within minutes.
- Access rules are a readable, standard file, tested in CI and at startup, with each version recorded.
- Each write makes one small query on `grants` and one in-process Cedar call.
- Group membership changes in Keycloak are outside nexus-api's audit trail.
- `cedarpy` is a thin community wrapper over Cedar's Rust core; it is pinned, and forked if it stalls.
- Records made before this change, and by internal paths with no caller, have no grants; only `SuperUser` may read or change them until it claims them.
- The owner-group pieces go: `owner_group`, `OWNER_GROUPS` and the chart's `ownerGroups`, `owner_group_of`, the `admin` role and the release route.

## Alternatives considered

### Keycloak holding all access

Keycloak Authorization Services can hold per-record access: a resource per record, user and time policies on it, and permissions, checked by the protection API or an authorization token. Done properly (a user policy with an expiry on the dataset's resource, not a client per access request as `develop` did), it is an intended Keycloak pattern.

| | Keycloak holds all access | This design |
|---|---|---|
| Where a grant lives | Keycloak resource, policy and permission | a row in nexus-api's database |
| Writing a grant | several Keycloak admin calls, no shared transaction with the record | one insert in the record's transaction |
| Renaming or deleting a record | Keycloak updated too, or left behind | grants go with the record |
| Revoking | minutes with short tokens and ended sessions; instant only with a Keycloak call per request | instant |
| Keycloak down | no writes, and no checks if checked per request | sign-in only; checks are local |
| Who can change access | anyone with the Keycloak console, outside nexus-api's audit trail | nexus-api routes only, with `created_by` |
| Tests | need a running Keycloak | unit tests and policy cases |
| Other services checking access | yes, from the token or Keycloak | through nexus-api |
| Familiar to hospital IT | yes, Keycloak is | Keycloak for sign-in; Cedar is new |

Keycloak alone wins on familiarity and on other services checking access directly. Neither is needed today: nexus-api is the only service that decides ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)). It loses on keeping two stores in step, which is where `develop` failed.

### Grants without Cedar

The same `grants` table with the rules written in Python (`if relation == "owner" or ...`) works, and installs nothing. Cedar is chosen because:

- **Deny by default:** nothing is allowed unless a `permit` matches; a forgotten branch in Python allows by accident.
- **Order does not matter:** a `forbid` always beats a `permit`; in Python a deny check below an early `return True` never runs.
- **One readable file:** the rules sit in one place a reviewer or a hospital's security team can sign off, instead of spreading into routes as `if caller.is_admin`.
- **Typos fail:** the schema rejects an unknown action, attribute or type in CI and at startup; in Python `"excute"` silently never matches.
- **A tested engine:** Cedar's evaluator has machine-checked proofs and is fuzz-tested against them; our tests cover our data, not the evaluator.
- **Sites can extend it:** a site adds a `.cedar` file through chart values; with Python rules a site would fork the code.

The cost is one dependency (`cedarpy`, no transitive dependencies, a prebuilt wheel) and building Cedar's input for each check.

### Why Cedar over the other engines

| Option | Runs in nexus-api | Standard rules format | Data in one place | Main reason not |
|---|---|---|---|---|
| **Cedar** | yes | yes | yes | small Python wrapper (pinned, forkable) |
| Open Policy Agent (Rego) | no, sidecar | yes, CNCF graduated | yes | extra container; Rego is hard to read |
| Cerbos | no, sidecar (in-process is paid) | yes, YAML | yes | extra container |
| Casbin | yes | no, Casbin-only | yes | generic table, rules held in memory |
| OpenFGA / SpiceDB | no, service | yes | no, second store | extra service, two places to keep in step |
| Keycloak Authorization Services | no, remote | yes | no, second store | see above |
| Oso (Polar) | was | yes | yes | open-source library dropped in 2023; now a paid service |
| Google CEL | yes | yes, expressions only | yes | no policy structure, schema or tests; we would build them. The fallback if Cedar is ruled out |

### Other alternatives

- **Owner groups from a configured `ownerGroups` list (the previous version of this ADR):** one lock per record, no per-user rights and no expiry.
- **Unix-like owner, group and mode columns on each record:** simple, but one group per record, mode bits that do not map to other engines, and access lists needed as soon as two groups need different rights.
- **Moving to OpenFGA later:** a strong fit if several services need access decisions or sharing nests deeply. Grants map one to one to its tuples, so the move stays open.
- **Cedar policy templates for grants:** Cedar's native way, but a template link cannot carry an expiry, and a plain table is easier to query and report on.

## Open questions

- Who may create groups and grant to them, and whether nexus-api should manage Keycloak group membership through its own routes.
- Whether sites may add `permit` rules or only `forbid` rules.
- The shape of the operator's `access` list, and whether UI grants and git grants may sit on the same record.
