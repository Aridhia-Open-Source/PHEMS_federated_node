# 0037. Keycloak authentication - roles and system accounts

Status: Proposed, 2026-11-20.

Keycloak is the OIDC provider the node ships ([0036](0036-api-authorization-oidc-authentication.md)). Each account holds one of five fixed realm roles, given by membership of a role group; the operator and Dagster sign in as Keycloak clients with client credentials. `SuperUser` bypasses grants, not the application's rules, and signs in with two factors.

## Context

- **0036 needs a provider** that issues signed tokens with a user id, one node role and groups, and that hands sign-in to a hospital's directory.
- **The chart already ships Keycloak** ([0017](0017-authorization-detached-from-dar-and-keycloak.md)), with kc-init setting up the realm.
- **Some callers are programs, not people.** The operator applies node config from git ([0032](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/700)) and Dagster writes pipeline state. Both must work from install, before nexus-api holds any rows, without a person's password.
- **Sites run their own directory.** Who is an admin is decided there, not in each node's Keycloak.
- **Records can be left without anyone responsible.** The responsible admin leaves, or a record was made before grants existed. Someone has to be able to recover them.
- **Bypassing access must not bypass the application.** Revoked flags and state transitions ([0005](0005-state-transition-tables.md), [0008](0008-enabled-revoked-and-soft-delete.md)) keep tasks and results consistent.

## Decision

### Keycloak

- **One realm per node,** loaded from `realms.json` and set up by kc-init on install and upgrade.
- **Realm, client and account names come from config, never fixed.** One chart value names the realm (default `FederatedNode`) for kc-init, nexus-api and Dagster, so several nodes can share one Keycloak, a realm each.
- **Sign-in can be handed on** to the hospital's directory, Entra ID or GitHub as a Keycloak identity provider; nexus-api sees the same three claims either way.
- **Groups are Keycloak groups** (for example `/studies/uc1`), managed in Keycloak or fed from the hospital's directory. A groups mapper in a default client scope puts them in every client's tokens, client-credentials tokens included.
- **Authorization Services are not used.** Keycloak holds nothing per record.

### Roles

Each account holds exactly one node role, a realm role. The roles are fixed in code; a site cannot add one. An account gets its role by joining that role's group, which carries the realm role, so a site can feed role membership from its directory (for example an Entra group mapped to `/roles/admins`).

| Role | Role group | Held by | What it is for |
|---|---|---|---|
| `SuperUser` | `/roles/superuser` | the break-glass account | recovering records: may read, change, delete, grant, claim and re-assign any record without a grant |
| `Administrator` | `/roles/admins` | admins, the first user included | setting up the node: creates global records and projects, assigns global records to projects |
| `Service` | `/roles/service` | the operator's client | applying node config from git; manages the records it creates |
| `Users` | `/roles/users` | normal users | the access their grants give them, nothing more |
| `Dagster` | `/roles/dagster` | the Dagster client | writing pipeline state, on the routes the pipeline calls only |

- **Exactly one node role per account.** nexus-api counts only the five node roles; Keycloak's built-in roles (`offline_access`, `default-roles-<realm>`) do not count. A token with no node role is a 401; a token with more than one is a 401 "account has more than one node role".
- **Roles do not reach records.** Grants name users and groups ([0038](0038-cedar-authorization-grants-and-policies.md)). A role matters in two places only: `SuperUser` skipping grants, and the routes `Dagster` may call. Rules for everyone in a role group (for example, admins may create global records) are Cedar rules on the group.
- **SuperUser bypasses grants, not the rules.** It may read, change, delete and grant any record without a grant, but the application's rules still apply to it. For example, nobody can run tasks on a revoked dataset, SuperUser included; it has to un-revoke the dataset first, like any other caller with `manage`. A state change that is a 409 for others is a 409 for it too.
- **SuperUser is for recovery, not daily work.** It is the only role that may claim a record or re-assign it to another user (`PUT <record path>/owner`), for example when the responsible admin has left. Every action it takes is recorded like any other caller's.
- **SuperUser signs in with two factors.** Keycloak's sign-in flows ask any account with `SuperUser` for a one-time code after the password, and the account sets one up at first sign-in.

### System accounts

- **kc-init creates them on install:** the first admin (in `/roles/admins`) and the superuser (in `/roles/superuser`) as users, and two confidential clients with service accounts: the operator's client (its service account in `/roles/service`) and Dagster's (in `/roles/dagster`).
- **Programs sign in with client credentials.** The operator and Dagster have no user and no password; each gets its token from its client id and secret. The superuser's password and each client's secret are Kubernetes Secrets referenced by name from values.
- **A program's records are managed through its role group.** Records the operator creates are `owned_by` its service account and give `manage` to `/roles/service` ([0038](0038-cedar-authorization-grants-and-policies.md)), so a rotated secret or a second operator client still manages them.

### Examples

The realm's roles, role groups, operator client and groups mapper (`realms.json`):

```json
"roles": {
  "realm": [
    { "name": "SuperUser" },
    { "name": "Administrator" },
    { "name": "Service" },
    { "name": "Users" },
    { "name": "Dagster" }
  ]
},
"groups": [
  { "name": "roles", "subGroups": [
    { "name": "superuser", "realmRoles": ["SuperUser"] },
    { "name": "admins", "realmRoles": ["Administrator"] },
    { "name": "service", "realmRoles": ["Service"] },
    { "name": "users", "realmRoles": ["Users"] },
    { "name": "dagster", "realmRoles": ["Dagster"] }
  ] }
],
"clients": [
  { "clientId": "fn-operator", "publicClient": false, "serviceAccountsEnabled": true, "standardFlowEnabled": false }
],
"users": [
  { "username": "service-account-fn-operator", "serviceAccountClientId": "fn-operator", "groups": ["/roles/service"] }
],
"clientScopes": [
  { "name": "groups", "protocol": "openid-connect", "protocolMappers": [
    {
      "name": "groups",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-group-membership-mapper",
      "config": { "claim.name": "groups", "full.path": "true", "access.token.claim": "true" }
    }
  ] }
],
"defaultDefaultClientScopes": ["roles", "profile", "email", "groups"]
```

The three claims nexus-api reads from a token; everything else is ignored, and so are Keycloak's built-in roles:

```json
{
  "sub": "5b1e7c2a-0d4f-4c1e-9a7b-2f3d8e6a1c90",
  "realm_access": { "roles": ["Users", "offline_access", "default-roles-federatednode"] },
  "groups": ["/roles/users", "/studies/uc1"]
}
```

The superuser and the operator's client from chart values, their credentials in Kubernetes Secrets named here:

```yaml
superuserSecret:
  name: fn-superuser          # Secret created by the site, never in values
  userKey: username
  passKey: password
operatorClientSecret:
  name: fn-operator-client
  clientIdKey: client-id
  clientSecretKey: client-secret
```

## Consequences

- The operator and Dagster work from the first install, with no manual Keycloak setup and no user passwords to rotate.
- A site manages who is an admin or a user in its own directory, through the role groups.
- Every node has a way to recover records whose responsible user has gone, without editing the database.
- The superuser's credentials are the most sensitive Secret on the node; a second factor protects them, and a site still has to keep them out of daily use.
- A new role needs a code change, a Cedar schema change and a review; a site cannot widen access by adding one in Keycloak.
- Hospital IT already know Keycloak, and sites can plug in their own directory without nexus-api changing.

## Alternatives considered

- **Another OIDC provider (Entra ID, Auth0, Dex).** Any provider with the three claims fits 0036. Keycloak is chosen because it runs inside the node, needs no cloud account, and can federate to each hospital's directory.
- **Realm roles mapped to each user directly.** Works, but a site's directory cannot feed them; role groups can be.
- **No superuser; administrators recover records.** Every admin would then need to bypass grants, which defeats per-record access between admins.
- **SuperUser bypasses everything, the application rules included.** Faster to recover with, but a run on a revoked dataset, or a state move the transition tables refuse, would leave tasks and results inconsistent. Un-revoking first costs one call.
- **Roles defined per site in Keycloak.** Flexible, but a role nexus-api does not know has no meaning in the Cedar policies, and the access model could drift per site without review.
- **Program accounts as ordinary admins.** Simpler, but the operator's records could then be edited through the UI and drift from git.

## Open questions

- Whether the superuser's use should raise an alert.
- Whether `Dagster` should become a grant-checked role once its routes are settled, instead of a fixed list of unchecked routes.
