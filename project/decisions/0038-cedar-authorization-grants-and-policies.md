# 0038. Cedar authorization - grants and policies

Status: Proposed, 2026-11-20.

This implements the authorization half of [0036](0036-api-authorization-oidc-authentication.md): nexus-api decides every access per record.

A `grants` table in nexus-api says which users and groups may read, assign, execute, write or manage each project and global record. A Cedar policy file says what each grant allows, and holds every rule that is the same for every record. Every route declares an `Access` check, through which a checked route receives its record, and nexus-api refuses to start if a route has none.

## Context

- **Config records say nothing about access.** Git providers, secrets, trigger and results repositories, datasets, projects and the project's assignments do not say who made them, who is responsible for them or who may change them. Any admin can change any record.
- **Some config is managed by a program.** The operator applies node config from files ([0032](0032-declarative-node-config-through-an-operator.md)); an edit by someone else is drift it has to fight.
- **Projects have members with different rights.** An admin sets up a study: global resources, projects, then users who mostly read, some who write and some who run tasks. People join and leave, and their rights change.
- **Approved data access requests are coming back with the task API trigger.** A data custodian approves a researcher to run tasks on a project until a date, and may revoke it.

## Decision

### Rules in Cedar, facts in the database

- **A rule that is the same for every record or node is a Cedar rule.** For example: admins and the operator may create global records; admins may assign any global record that is not restricted; SuperUser skips grants.
- **The database holds only per-record facts:** grants, `created_by` and `owned_by`, `revoked`, `restricted`. Nothing is seeded on install, and there is no `system` user.

### Tables and columns

- **`grants`:** which user or group may do what to which record:

  ```
  grants
    id            serial pk
    object_type   text        -- the model's authz_type: 'Project', 'Dataset', ...
    object_id     int
    relation      text        -- 'read' | 'assign' | 'execute' | 'write' | 'manage'
    subject_type  text        -- 'user' | 'group'
    subject_id    text        -- Keycloak user id or group path
    expires_at    timestamptz null
    created_by    text        fk users.id
    created_at    timestamptz
    unique (object_type, object_id, relation, subject_type, subject_id)
  ```

  `object_type`, `relation` and `subject_type` are checked against fixed lists. `object_id` has no foreign key, since it points at many tables; deleting a record deletes its grants in the same transaction.
- **Grants sit on projects and global records only.** A project is a set of resources with one set of permissions: its secrets, trigger and results repositories and assignments have no grants of their own, and every check on them is a check on the project. Each of those resources records `created_by`.
- **Projects and global records get `created_by` and `owned_by`** (both fk `users.id`). `created_by` is set once, on create, for audit. `owned_by` is who is responsible for the record now; it changes when SuperUser claims or re-assigns the record. Neither grants anything; powers come only from grants and Cedar rules.
- **Global records (datasets, git providers, secrets, trigger and results repositories) get `restricted`** (boolean, default false). A restricted record is not assignable by every admin, only by those with a grant.
- **`users`:** one row per Keycloak account that has called nexus-api (`id` the Keycloak user id, `username`, `created_at`, `last_seen_at`), upserted from the token on each call and skipped when seen in the last minute. Service accounts have rows like people. Never deleted.
- **`policy_versions`:** the hash and contents of the policy files nexus-api started with, one row per new hash, for audit.
- **Each model with grants declares `authz_type`** (`authz_type = "Dataset"`), stored in grants and used in the policies. It is never derived from the class or table name, so renaming either breaks nothing. `OwnedMixin` fails at import if a model leaves it out.

### Permissions

`read` < `assign`, `execute`, `write` (each includes `read`) < `manage`.

| Relation | Allows |
|---|---|
| `manage` | everything (read, assign, execute, write, delete), plus adding and removing the record's grants, `manage` included |
| `write` | change or delete it; read it |
| `execute` | run tasks with it; read it |
| `assign` | add it to a project (a project assignment) without changing it; read it |
| `read` | read it |

Every action, reads included, is checked. Several users and groups may hold `manage` on one record.

### Where grants come from

- **Nobody writes the table directly.** Grants come only from the paths below.
- **The creator manages what they create.** On creating a project or a global record, nexus-api sets `created_by` and `owned_by` to the caller and adds a `manage` grant for them, in the same transaction as the record.
- **The operator's records are managed by its role group.** A record the operator creates is `owned_by` the operator client's service account, and the `manage` grant goes to group `/roles/service`, so a second operator client manages it too.
- **The `owned_by` user always holds `manage`.** The grant that gives it cannot be removed while they own the record; change `owned_by` first.
- **Approving a data access request** adds an `execute` grant with an expiry; revoking deletes it.
- **On delete,** the record's grants go too.

### Global

`Global` is the container for global records, as a project is for project records. Creating a global record (a dataset, git provider, secret, trigger or results repository, or a project) needs `write` on `Global`; a Cedar rule gives it to `/roles/admins` and `/roles/service`. `Global` is not a table and has no grants; it is `Global::"0"` in Cedar and the parent of every dataset, git provider, secret, trigger and results repository. Projects are created under it but are not its children.

### Grant routes, claiming and re-assigning

- **Routes on each project and global record:**
  - `GET <record path>/grants` lists them;
  - `POST <record path>/grants` adds one (`relation`, `subject_type`, `subject_id`, `expires_at`);
  - `DELETE <record path>/grants/{id}` removes one.
- **Only a `manage` holder, or `SuperUser`, may add or remove a record's grants.** Assigning users and groups to a project is the responsible admin's job; a user with `write` cannot grant access to others.
- **Claiming and re-assigning:** `PUT <record path>/owner` sets `owned_by` and gives the new owner `manage`. With no body it names the caller (claiming); with a user id it names that user, for example when the responsible admin leaves. Only `SuperUser` may call it. The former owner's `manage` grant stays until a `manage` holder removes it.

### Policies: Cedar files in the repo

- **The rules are Cedar policies** ([cedar-policy/cedar](https://github.com/cedar-policy/cedar)), evaluated in-process by `cedarpy`. Cedar stores nothing; nexus-api passes in what each request needs.
- **Nothing is allowed unless a `permit` matches,** and a `forbid` always wins.
- **Files:** `nexus/api/authz/policies.cedar` (the rules), `schema.cedarschema` (entity types, attributes and actions) and `cases.yaml` (allow and deny cases), committed, reviewed by PR and built into the image.
- **Tested:** CI validates the policies against the schema and runs `cases.yaml` in pytest. At startup nexus-api validates them again, refuses to start if they fail, and writes a `policy_versions` row if the hash is new.
- **The standard rules:**

  ```
  // manage allows everything, including changing the record's grants.
  permit (principal, action, resource)
  when { context.grants has manage && context.grants.manage > context.now };

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

  // Admins and the operator may create global records.
  permit (principal in Group::"/roles/admins", action == Action::"write", resource == Global::"0");
  permit (principal in Group::"/roles/service", action == Action::"write", resource == Global::"0");

  // Admins may read and assign any global record...
  permit (principal in Group::"/roles/admins", action in [Action::"read", Action::"assign"], resource in Global::"0");

  // ...unless it is restricted and they hold no assign or manage grant on it.
  forbid (principal in Group::"/roles/admins", action == Action::"assign", resource in Global::"0")
  when { resource.restricted }
  unless {
    (context.grants has assign && context.grants.assign > context.now) ||
    (context.grants has manage && context.grants.manage > context.now)
  };

  // SuperUser may do anything.
  permit (principal in Role::"SuperUser", action, resource);

  // Nobody runs tasks on a revoked dataset.
  forbid (principal, action == Action::"execute", resource is Dataset)
  when { resource.revoked };
  ```

- **SuperUser bypasses grants, not the rules** ([0037](0037-keycloak-authentication-roles-and-system-accounts.md)): the `permit` for `SuperUser` skips grants, and every `forbid` still applies to it.
- **Sites add rules later** as extra `.cedar` files through chart values, versioned in the site's repo ([0031](0031-gitops-delivery-with-helm-and-flux.md)). They add to the standard rules and cannot remove them. A new action needs code, since a route has to ask for it.

### The check

- **Every write route declares an `Access` dependency** (`app/helpers/authz.py`), with keyword arguments only:

  ```python
  class Action(StrEnum):
      READ = "read"
      WRITE = "write"
      EXECUTE = "execute"
      ASSIGN = "assign"
      MANAGE = "manage"         # changing the record's grants
      UNCHECKED = "unchecked"   # no record check; the route has no record

  @router.patch("/{dataset_id}")
  def patch_dataset(dataset: Dataset = Depends(Access(model=Dataset, action=Action.WRITE))):

  # gets a token; no record yet
  @router.post("/login", dependencies=[Depends(Access(action=Action.UNCHECKED))])
  def login(body: LoginBody):
  ```

  `Access` raises at import if `model` is missing for a checked action or given with `Action.UNCHECKED`. Every `Action` except `UNCHECKED` must exist in the Cedar schema, checked at startup. An unchecked route gives its reason in a comment above it.
- **Deny by default, checked at startup.** `create_app` walks every route, reads included, and refuses to start if one has no `Access` dependency, as `OPEN_ROUTERS` does for scopes today. A forgotten check stops nexus-api from starting, so it fails every test run and every deploy, not only one test. Today's unchecked routes are the health checks, login, token refresh, a user's own password reset, and Dagster's pipeline state writes; a snapshot test lists them, so a new one shows up in review.
- **A checked route only receives its record through the check,** so it cannot use one unchecked. A deny is a 409 naming the record's `owned_by` user. `Access`:
  1. loads the record from the path (404 if missing);
  2. reads the caller from the token: user id, node role, groups;
  3. loads the caller's grants on the record (one query on `grants` matching the user or any of its groups), as one expiry per relation;
  4. builds the Cedar request: the user with its role and groups as parents, the record with its attributes (`revoked`, `restricted`, and `Global` as parent for the five global record types), and `context` with the grants and the time;
  5. returns the record if Cedar allows, and raises otherwise.

  An unchecked route needs no token from `Access`. Code that is not a route (cascades, the grants routes) calls the same check as `can(caller, action, record)`.
- **Scopes stay coarse.** A route still requires its token scope first; the record check comes after.
- **Creates check their parent.** A record that does not exist yet is checked through the record it is created under:
  - creates inside a project (a project's secret, trigger repository or results repository) need `write` on the project, and so do changes and deletes of them: `Access(model=Project, action=Action.WRITE)`;
  - global creates (datasets, git providers, secrets, trigger and results repositories, projects) need `write` on `Global`, `Access(model=Global, action=Action.WRITE)`.

  Who may create global records is then a Cedar rule, not only a Keycloak scope.
- **Assigning needs both sides.** Adding or removing a project's datasets, secrets, trigger repositories or results repository needs `write` on the project (through `Access`) and `assign` on the global record (through `can()`).
- **Lists show only what the caller may read.** List routes filter their query by the caller's grants (a join on `grants` for the user or its groups) and by the Cedar rules that need no grant (global records for admins), then Cedar checks each row; `SuperUser` sees everything.
- **Cascading deletes check every record they would delete;** if the caller may not write one, nothing is deleted.
- **`execute` is checked for tasks requested through the API.** Tasks started by merged pull requests are not checked, for now; the trigger repository's permissions and the pull request review are the gate there:
  - nexus-api cannot tell who raised or merged a pull request until a hospital links GitHub or Azure identities to Keycloak, and most sites have not yet;
  - it is not settled whether the raiser or the merger should need `execute`; if it is the merger, the right to merge already is the permission.
- **A test walks every checked write route** and checks it answers a 409 to a caller without the grant and leaves the record unchanged.

### With Flux and the operator

The site's git repository already drives the node: Flux deploys the chart ([0031](0031-gitops-delivery-with-helm-and-flux.md)) and the operator applies node config through nexus-api ([0032](0032-declarative-node-config-through-an-operator.md)). Access fits the same flow:

- **Config managed by the operator.** The operator calls nexus-api with its client credentials, so every record it applies is `owned_by` its service account, with `manage` for `/roles/service`. Admins can still read and assign those records, but a UI edit by an admin is a 409: the records cannot drift from git. Changing one means a PR to the site repository, or the superuser claiming it in an emergency, after which the operator reports drift.
- **Policies from git.** A site's extra `.cedar` files are chart values in its Flux repository, changed by PR. Flux rolls them out; nexus-api validates them at startup, so a bad policy fails the rollout and the previous pods keep serving.
- **Standing access from git.** An operator resource can declare who may use it, for example a Project with `access: [{group: uc1-team, relation: read}]`. The operator reconciles that list through the `/grants` routes, which it may call because `/roles/service` manages the record; removing a line from git removes the grant. Other users get `read` or `assign` on operator records this way.
- **Groups, not users, in git.** Git names groups (`uc1-team`); membership stays in Keycloak or the hospital's directory, so no Keycloak user ids are committed.
- **Decisions on the day stay at runtime.** Approving a data access request, with its expiry, is a grant made through the API, not a PR. Its `created_by` and the audit trail record who approved it.
- **Rules versioned with the node.** `policy_versions` records the hash of the policies each pod started with, so any decision can be traced to the commit that set the rules.

The operator's `access` list is designed when the operator work resumes; nothing here depends on it.

### An example

- The operator creates dataset 12: `owned_by` the operator's service account; grant `Dataset 12, manage, group /roles/service`.
- Dana (in `/roles/admins`) creates project 3: `owned_by` dana; grant `Project 3, manage, user dana`.
- Dana adds dataset 12 to project 3: allowed (`manage` on the project, and the Cedar rule letting admins assign unrestricted global records). She renames dataset 12: denied, the operator manages it.
- In Keycloak she adds Alice and Bob to group `/studies/uc1`. In nexus-api she grants `/studies/uc1` `read`, Alice `write`, and Bob `execute` until 2027-03-01.
- Alice edits project 3: allowed. Bob edits it: denied. Bob runs a task: allowed, until March. Alice tries to grant access to someone: denied, only `manage` holders may.
- Dana removes Alice from `/studies/uc1`: Alice keeps her own `write` grant, which also lets her read.
- Dana leaves the hospital: SuperUser re-assigns project 3 to Erin, who becomes `owned_by` and gets `manage`.

## Consequences

- Every project and global record has a creator and a responsible user, and the UI can show who may do what.
- The operator's records cannot drift through the UI: only `/roles/service` and the superuser manage them.
- Approving and revoking access is one row in nexus-api's own transaction.
- Access rules are a readable, standard file, tested in CI and at startup, with each version recorded.
- Each write makes one small query on `grants` and one in-process Cedar call.
- `cedarpy` is a thin community wrapper over Cedar's Rust core; it is pinned, and forked if it stalls.
- Records made by internal paths with no caller have no grants; only `SuperUser`, and admins through the global rules, reach them until SuperUser claims them.
- Leavers' records stay where they are until SuperUser re-assigns them.
- Every rule that applies to all records is in one reviewed file; the database has no seed rows to drift between sites.
- The owner-group pieces go: `owner_group`, `OWNER_GROUPS` and the chart's `ownerGroups`, `owner_group_of`, the `admin` role and the release route.

## Alternatives considered

### Grants without Cedar

The same `grants` table with the rules written in Python (`if relation == "manage" or ...`) works, and installs nothing. Cedar is chosen because:

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
| Keycloak Authorization Services | no, remote | yes | no, second store | see [0036](0036-api-authorization-oidc-authentication.md) |
| Oso (Polar) | was | yes | yes | open-source library dropped in 2023 for a paid service |
| Google CEL | yes | yes, expressions only | yes | no policy structure, schema or tests; we would build them. The fallback if Cedar is ruled out |

### Open Policy Agent

OPA is the closest rival: the policy engine most Kubernetes clusters already run (through Gatekeeper). Both read the same `grants` table, so the choice is the engine, not the data.

| | Cedar | OPA (Rego) |
|---|---|---|
| Where it runs | inside nexus-api | a sidecar container, one network call per check |
| Reading the rules | short `permit` and `forbid` statements a security team can sign off | Rego is powerful but hard to read and easy to get subtly wrong |
| Typos | the schema rejects them in CI and at startup | no schema by default; a typo silently never matches |
| Engine assurance | machine-checked proofs, fuzz-tested | widely used and tested, no formal proofs |
| Maturity | small Python wrapper (`cedarpy`), smaller community | graduated CNCF project, large ecosystem and tooling |
| Familiar to hospital IT | new | likely, where a site already runs Gatekeeper |
| Reach | nexus-api only | one engine could cover cluster and application policy |

OPA wins on maturity and familiarity. Cedar is chosen because it needs no extra container, and its rules are readable and checked against a schema. Neither of OPA's strengths is needed while nexus-api is the only service that decides access ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)).

### Other alternatives

- **Owner groups from a configured `ownerGroups` list:** one lock per record, no per-user rights and no expiry.
- **Grants to roles, and seeded grants for admins and the operator:** puts a node-wide rule in rows on every node and record, where a site can change it without review; a Cedar rule on the role group says it once.
- **An `owner` relation that `owned_by` implies:** mixes who is responsible with what they may do; `owned_by` grants nothing, and `manage` is an ordinary grant several users and groups can hold.
- **Unix-like owner, group and mode columns on each record:** simple, but one group per record, mode bits that do not map to other engines, and access lists needed as soon as two groups need different rights.
- **Moving to OpenFGA later:** a strong fit if several services need access decisions or sharing nests deeply. Grants map one to one to its tuples, so the move stays open.
- **Cedar policy templates for grants:** Cedar's native way, but a template link cannot carry an expiry, and a plain table is easier to query and report on.

## Open questions

- Who may create groups and grant to them.
- Who may set or clear `restricted` on a global record.
- Whether sites may add `permit` rules or only `forbid` rules.
- The shape of the operator's `access` list, and whether UI grants and git grants may sit on the same record.
