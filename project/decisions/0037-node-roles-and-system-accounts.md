# 0037. Node roles and system accounts

Status: Proposed, 2026-11-20.

## Context

- **Keycloak signs people and programs in** ([0017](0017-authorization-detached-from-dar-and-keycloak.md)); nexus-api decides what they may do to each record ([0036](0036-keycloak-for-authentication-nexus-api-for-authorization.md)), through grants ([0038](0038-policy-based-access-control-with-grants-and-cedar.md)).
- **Some callers are programs, not people.** The operator applies node config from git ([0032](0032-declarative-node-config-through-an-operator.md)) and Dagster writes pipeline state. Both must work from install, before nexus-api holds any rows.
- **Records can be left without an owner.** The owning admin leaves, or a record was made before grants existed. Someone has to be able to recover them.
- **Bypassing access must not bypass the application.** Revoked flags and state transitions ([0005](0005-state-transition-tables.md), [0008](0008-enabled-revoked-and-soft-delete.md)) keep tasks and results consistent; a role that skipped them could leave a node in a broken state.

## Decision

Each account holds exactly one node role, a Keycloak realm role. The roles are fixed in code; a site cannot add one.

| Role | Held by | What it is for |
|---|---|---|
| `SuperUser` | the break-glass account | recovering records: may read, change, delete, grant and claim any record without a grant |
| `Administrator` | admins, the first user included | setting up the node: creates global records and projects, assigns global records to projects |
| `Service` | the nexus operator | applying node config from git; owns the records it creates |
| `Users` | normal users | the access their grants give them, nothing more |
| `Dagster` | the Dagster account | writing pipeline state, on the routes the pipeline calls only |

- **kc-init creates the system accounts on install:** the first admin, the superuser, the operator account and the Dagster account. Their passwords are Kubernetes Secrets referenced by name from values.
- **A role gives broad scopes, not per-record access.** Per-record access is a grant. A role reaches a record only through a grant to that role (for example `role:Service` owns what the operator creates) or, for `SuperUser`, through the one Cedar rule that skips grants.
- **SuperUser bypasses grants, not the rules.** It may read, change, delete and grant any record without a grant, but the application's rules still apply to it. For example, nobody can run tasks on a revoked dataset, SuperUser included; it has to un-revoke the dataset first, like any owner. A state change that is a 409 for others is a 409 for it too.
- **SuperUser is for recovery, not daily work.** It is the only role that may claim a record (`PUT <record path>/owner`, [0038](0038-policy-based-access-control-with-grants-and-cedar.md)), for example when the owning admin has left. Every action it takes is recorded like any other caller's.
- **Program accounts own through their role.** Records the operator creates are owned by `role:Service`, not by the operator's user, so a rotated or second operator account still owns them.

## Consequences

- The operator and Dagster work from the first install, with no manual Keycloak setup.
- Every node has a way to recover records whose owner has gone, without editing the database.
- The superuser's credentials are the most sensitive Secret on the node; a site has to keep them out of daily use.
- A new role needs a code change, a Cedar schema change and a review; a site cannot widen access by adding one in Keycloak.

## Alternatives considered

- **No superuser; administrators recover records.** Every admin would then need to bypass grants, which defeats per-record ownership between admins.
- **SuperUser bypasses everything, the application rules included.** Faster to recover with, but a run on a revoked dataset, or a state move the transition tables refuse, would leave tasks and results inconsistent. Un-revoking first costs one call.
- **Roles defined per site in Keycloak.** Flexible, but a role nexus-api does not know has no meaning in the Cedar policies, and the access model could drift per site without review.
- **Program accounts as ordinary admins.** Simpler, but the operator's records could then be edited through the UI and drift from git.

## Open questions

- Whether superuser sign-in should need a second factor or an approval, and whether its use should raise an alert.
- Whether `Dagster` should become a grant-checked role once its routes are settled, instead of a fixed list of unchecked routes.
