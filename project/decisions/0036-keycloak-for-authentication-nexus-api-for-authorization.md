# 0036. Keycloak for authentication, nexus-api for authorization

Status: Proposed, 2026-11-20.

Keycloak authenticates: it holds the accounts, gives each one a broad role and its groups, and issues tokens. nexus-api authorizes: it decides every access to every record, from its own database, in the record's own transaction, by rules in one reviewed policy file. Keycloak holds nothing per record. The implementation is [0038](0038-policy-based-access-control-with-grants-and-cedar.md).

## Context

- **Keycloak signs people in.** It holds the accounts, their realm roles and groups, and issues the tokens nexus-api checks ([0017](0017-authorization-detached-from-dar-and-keycloak.md)). At a site it can also hand sign-in to the hospital's directory, GitHub or Entra ID.
- **A record's rules belong to nexus-api** ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)).
- **The legacy `develop` backend kept access in Keycloak Authorization Services.** It stored a Keycloak resource, policy and permission per dataset, a Keycloak client and user per data access request, and checked every call in the `@auth` decorator (`webserver/app/helpers/wrappers.py`).

### Why the legacy design falls short

- **Up to five Keycloak calls per request.** Keycloak being slow or down stopped every call.
- **The record checked was guessed, not loaded.** The decorator took the dataset from the URL, then from any `dataset_id` in the body, so the record checked was not always the record changed.
- **The client chose the access request** through a `project-name` header.
- **Rules were split and hidden** between role names hard-coded in the decorator and Keycloak configuration that `realms.json` did not fully apply.
- **Two stores, no transaction.** A failure part way left Keycloak and the database apart; deletes and renames left Keycloak behind.
- **Only datasets had per-record rules.** Projects, secrets and repositories had none.
- **Revoking lagged** until tokens already issued expired.

| Legacy | Here |
|---|---|
| Keycloak calls on every request | none; the token is checked locally and access is decided in nexus-api |
| record guessed from URL or body | nexus-api loads the record it checks |
| client header picks the access request | access names the user; nothing is read from headers |
| rules in code and Keycloak config | one policy file, validated and tested |
| two stores without a transaction | access lives in the record's own database and transaction |
| datasets only | every owned record type |
| revoke waits for token expiry | revoking applies at once |

### Why before the operator and Flux

This lands before the operator ([0032](0032-declarative-node-config-through-an-operator.md)) and Flux delivery ([0031](0031-gitops-delivery-with-helm-and-flux.md)), because both build on the access model. The operator creates records and needs an identity to own them, and Flux copies each site's config, access settings included, into that site's GitOps repository. The single baseline migration ([0023](0023-fastapi-replaces-flask.md)) is cheap to change only until a site runs it. Settled after the first rollout, the old model ships to every hospital and has to be migrated out site by site. Without per-record access, the node cannot be governed: owner groups give no per-user rights, no expiry and no instant revoke, so leavers and finished projects keep access until someone edits Keycloak by hand, which fails the access controls sites audit before approving a node.

- **The operator needs an identity.** It creates projects, datasets and secrets. It gets the `Service` role ([0037](0037-node-roles-and-system-accounts.md)) and owns its records through grants ([0038](0038-policy-based-access-control-with-grants-and-cedar.md)); without them it ships on `ownerGroups` and `admin`, which 0038 removes.
- **The baseline closes at first rollout.** Grants change the schema, so they belong in the baseline, not in a later data migration on live hospital databases.
- **Flux fixes config in site repositories.** Values like `ownerGroups` end up in every site's repository; dropping them later is a rollout to each site, not one PR.
- **The rework is already planned.** The operator moves onto this model either way. Before merge that is a few files; after rollout it is code, data and site config together.
- **Sites ask first.** "Who can see this dataset, and can you revoke it?" Grants answer with instant revoke and an audit trail, which [0021](0021-nexus-api-owns-the-record-and-the-rules.md) makes nexus-api's job.

## Decision

### Keycloak: accounts, roles and groups

- **Each account holds one node role,** a realm role: `SuperUser`, `Administrator`, `Service`, `Users` or `Dagster`. The roles, who holds them and the accounts kc-init creates are in [0037](0037-node-roles-and-system-accounts.md).
- **Groups are Keycloak groups** (for example `/studies/uc1`). Admins manage membership in Keycloak; later a hospital's directory groups can feed them. The realm has a groups mapper, so tokens carry the caller's groups.
- **Keycloak holds nothing per record.** Keycloak Authorization Services are not used.

### nexus-api: every access decision

- **nexus-api decides every access to every record,** reads included, from the caller's token and its own database. It makes no Keycloak call to decide.
- **Access is data in nexus-api's database,** written in the same transaction as the record it is about, and only through nexus-api's routes.
- **The rules are one policy file in the repo,** reviewed by PR, tested in CI and checked at startup.
- **How:** grants, Cedar policies and the `Access` check are in [0038](0038-policy-based-access-control-with-grants-and-cedar.md).

## Consequences

- Keycloak being down stops sign-in only; checks are local to nexus-api.
- Access changes are in nexus-api's audit trail. Revoking applies at once; removing someone from a Keycloak group applies when their token next refreshes, within minutes.
- Group membership changes in Keycloak are outside nexus-api's audit trail.
- Access rules sit in one readable file, and tests need no running Keycloak.
- Other services cannot check access themselves; they ask nexus-api.

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

## Open questions

- Whether nexus-api should manage Keycloak group membership through its own routes.
