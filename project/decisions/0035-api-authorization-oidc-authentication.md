# 0035. API authorization, OIDC authentication

Status: Proposed, 2026-11-20.

An OpenID Connect (OIDC) provider authenticates: it holds the accounts, gives each one a node role and its groups, and issues the tokens. nexus-api authorizes: it decides every access to every record, from its own database, in the record's own transaction, by rules in one reviewed policy file. The provider holds nothing per record. The provider we ship is Keycloak ([0036](0036-keycloak-authentication-roles-and-system-accounts.md)); the rules are Cedar ([0037](0037-cedar-authorization-grants-and-policies.md)).

## Context

- **A record's rules belong to nexus-api** ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)).
- **Sites sign in through their own directory.** A hospital may use Entra ID, LDAP or GitHub; the node must not depend on which.
- **The legacy `develop` backend kept access in the identity provider,** in Keycloak Authorization Services: a resource, policy and permission per dataset, a client and user per data access request, checked on every call by the `@auth` decorator (`webserver/app/helpers/wrappers.py`). It falls short:
  - **Up to five provider calls per request;** the provider being slow or down stopped every call.
  - **The record checked was guessed, not loaded,** from the URL, then from any `dataset_id` in the body.
  - **The client chose the access request** through a `project-name` header.
  - **Rules were split and hidden** between role names in the decorator and provider config that `realms.json` did not fully apply.
  - **Two stores, no transaction:** a failure part way left the provider and the database apart; deletes and renames left the provider behind.
  - **Only datasets had per-record rules,** and **revoking lagged** until issued tokens expired.

### Why before the operator and Flux

This lands before the operator ([0032](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/700)) and Flux delivery ([0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/701)), because both build on the access model. The operator creates records and needs an identity to be responsible for them, and Flux copies each site's config, access settings included, into that site's GitOps repository. The single baseline migration ([0023](0023-fastapi-replaces-flask.md)) is cheap to change only until a site runs it. Settled after the first rollout, the old model ships to every hospital and has to be migrated out site by site. Without per-record access, the node cannot be governed: owner groups give no per-user rights, no expiry and no instant revoke, so leavers and finished projects keep access until someone edits the provider by hand, which fails the access controls sites audit before approving a node.

- **The operator needs an identity.** It signs in as a Keycloak client in the `Service` role group ([0036](0036-keycloak-authentication-roles-and-system-accounts.md)) and manages its records through a grant to that group ([0037](0037-cedar-authorization-grants-and-policies.md)); without them it ships on `ownerGroups` and `admin`, which 0037 removes.
- **The baseline closes at first rollout.** Grants change the schema, so they belong in the baseline, not in a later data migration on live hospital databases.
- **Flux fixes config in site repositories.** Values like `ownerGroups` end up in every site's repository; dropping them later is a rollout to each site, not one PR.
- **Sites ask first.** "Who can see this dataset, and can you revoke it?" Grants answer with instant revoke and an audit trail.

## Decision

### Authentication: what the provider supplies

- **Signed tokens, checked locally.** nexus-api verifies each token against the provider's published keys; it makes no provider call to decide access.
- **Issuer and key address are configured separately.** The token's issuer is checked against the provider's public address; the signing keys are fetched over the in-cluster one. Nothing assumes one node per cluster.
- **Three claims:** a stable user id (`sub`), exactly one node role, and the caller's groups. Nothing else is read from the token; the provider's built-in roles are ignored.
- **Client accounts for programs:** the operator and Dagster sign in as provider clients with client credentials, with no user and no password; each client's service account holds a node role. They are created on install.
- **Nothing per record.** No resources, policies or permissions live in the provider.
- **Access tokens on every request.** Clients send the access token to nexus-api; a refresh token only ever goes to the provider, to get a new access token. `/login` returns both. Programs (Dagster, the operator) can log in again with their client credentials instead of refreshing.

### Authorization: nexus-api decides

- **Every access to every record,** reads included, is decided in nexus-api from the token's three claims and its own database.
- **Access is data in nexus-api's database,** written in the record's own transaction, and only through nexus-api's routes.
- **The rules are one policy file in the repo,** reviewed by PR, tested in CI and checked at startup.

| Legacy | Here |
|---|---|
| provider calls on every request | none; the token is checked locally |
| record guessed from URL or body | nexus-api loads the record it checks |
| client header picks the access request | access names the user; nothing is read from headers |
| rules in code and provider config | one policy file, validated and tested |
| two stores without a transaction | access lives in the record's own transaction |
| datasets only | every owned record type |
| revoke waits for token expiry | revoking applies at once |

## Consequences

- The provider being down stops sign-in only; checks are local.
- Swapping the provider needs only the three claims; the access model does not change.
- Access changes are in nexus-api's audit trail; group membership changes in the provider are not.
- Revoking a grant applies at once; removing someone from a group applies when their token next refreshes, within minutes.
- Other services cannot check access themselves; they ask nexus-api.

## Alternatives considered

### The provider holding all access

Keycloak Authorization Services, done properly (a user policy with an expiry on the dataset's resource, not a client per access request as `develop` did), is an intended Keycloak pattern.

| | Provider holds all access | This design |
|---|---|---|
| Writing a grant | several admin calls, no shared transaction with the record | one insert in the record's transaction |
| Renaming or deleting a record | provider updated too, or left behind | grants go with the record |
| Revoking | minutes, or a provider call per request | instant |
| Provider down | no writes, and no checks if checked per request | sign-in only |
| Who can change access | anyone with the provider console, outside the audit trail | nexus-api routes only, with `created_by` |
| Tests | need a running provider | unit tests and policy cases |
| Other services checking access | yes, directly | through nexus-api |
| Swapping the provider | access must be migrated | three claims |

The provider wins on other services checking access directly, which is not needed while nexus-api is the only service that decides ([0021](0021-nexus-api-owns-the-record-and-the-rules.md)). It loses on keeping two stores in step, which is where `develop` failed.

## Open questions

- Whether nexus-api should manage group membership through its own routes.
