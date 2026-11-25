# Sign-in and roles

How people and programs sign in to a Federated Node 2.x, and what each of the five roles is for. What a person may do to a project or dataset is a separate question: see [Granting access](./Granting-Access).

The design is in [ADR 0035](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0035-api-authorization-oidc-authentication.md) and [ADR 0036](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0036-keycloak-authentication-roles-and-system-accounts.md).


## How sign-in works

Keycloak keeps the accounts and issues the tokens. nexus-api decides what each account may do, from its own database. Keycloak holds nothing per project or dataset.

1. `POST /login` with a username and password returns an access token and a refresh token ([Using the API](./Using-The-API#authentication)).
2. Send the access token as the Bearer on every call. It lasts 5 minutes.
3. When it expires, swap the refresh token for a new pair at `POST /refresh_token`. The refresh token lasts for the session (chart value `token.life`, 8 hours by default).

nexus-api checks each token itself against Keycloak's published keys, so a call does not wait on Keycloak. If Keycloak is down, nobody can sign in, but people already signed in keep working until their token expires.

nexus-api reads three things from a token: the user id, the one node role, and the groups. Nothing else in it matters. That is also why a hospital can hand sign-in to its own directory (Entra ID, GitHub, LDAP) as a Keycloak identity provider without anything else changing.


## The five roles

An account holds exactly one node role. A token with none, or with more than one, is refused with a `401`. The roles are fixed: a site cannot add one in Keycloak.

| Role | Held by | What it is for |
|---|---|---|
| `SuperUser` | the break-glass account | Recovering records: may read, change, delete, grant, claim and re-assign any project or global record, without a grant |
| `Administrator` | admins, the first user included | Setting up the node: creates global records and projects, and assigns global records to projects |
| `Service` | the operator | Applying node config from git, and managing the records it creates |
| `Users` | normal users | Whatever their [grants](./Granting-Access) give them, nothing more |
| `Dagster` | the Dagster account | Writing pipeline state, on the routes the pipeline calls only |

`SuperUser` is for recovery, not daily work. It skips grants, but the application's rules still apply to it: nobody can run a task on a revoked dataset, `SuperUser` included.


## Role groups and groups

Each role is a Keycloak group, and an account gets its role by joining it:

| Role | Group |
|---|---|
| `SuperUser` | `/roles/superuser` |
| `Administrator` | `/roles/admins` |
| `Service` | `/roles/service` |
| `Users` | `/roles/users` |
| `Dagster` | `/roles/dagster` |

So a site decides who is an admin in its own directory: map a directory group to `/roles/admins`.

Other Keycloak groups, for example `/studies/uc1`, are for [grants](./Granting-Access): give a group access to a project once, and add or remove people in Keycloak.


## Creating users

An admin creates a user with `POST /global/users` ([Using the API](./Using-The-API#users)). The role is `Users`, or `Administrator`, which only the `SuperUser` may give. Researchers who only work in git do not need an account.


## Not yet shipped

The operator's own account is planned as a Keycloak client with no password, in `/roles/service` ([ADR 0036](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0036-keycloak-authentication-roles-and-system-accounts.md)); it arrives with the operator. Dagster signs in as a Keycloak user for now.
