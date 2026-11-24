# Auth setup for operators

What to set when you install a node: the first admin, the break-glass superuser, and the realm. For what the roles mean, see [Sign-in and roles](./Sign-In-And-Roles).


## The first admin

`firstUserSecret` creates the first admin, in `/roles/admins`. The password is a Secret you create; the rest is in values ([Deploy: Core](./Deploy-Core#3-create-the-namespace-and-the-secrets-you-must-provide)):

```yaml
firstUserSecret:
  name: fn-first-user
  passKey: password
  email: admin@your-institution.example.com
  firstName: Admin
  lastName: User
```

The account is created once. Changing the Secret later does not reset the password: that is the person's account.


## The break-glass superuser

`superuserSecret` creates the `SuperUser`, in `/roles/superuser`. Both the username and the password come from a Secret you create, never from values:

```yaml
superuserSecret:
  name: fn-superuser
  userKey: username
  passKey: password
```

```sh
kubectl create secret generic fn-superuser -n federated-node \
  --from-literal=username=break-glass \
  --from-literal=password='<a long random password>'
```

Leave it out and the node has no way to recover a record whose owner has left, short of editing the database.

- It is created once, like the first admin.
- It has a password only, no second factor yet. Keep it out of daily use and treat the Secret as the most sensitive one on the node.
- Use it to [claim or re-assign a record](./Granting-Access#when-the-owner-leaves) and little else.


## The realm

`keycloak.realm` names the realm the node's users, roles and clients live in (default `FederatedNode`). Keycloak, the realm setup job and nexus-api all read it from there, so several nodes can share one Keycloak with a realm each. Changing it on an existing node starts a new, empty realm.

Tokens are issued for the node's host (`https://<host>/keycloak`), so `host` must be the address people use.


## Hand sign-in to your directory

Add Entra ID, GitHub or LDAP as an identity provider in the Keycloak admin console, then put the people who should be admins in the `/roles/admins` group (or map a directory group to it). nexus-api sees the same three claims either way.


## Upgrading from an older 2.x

Earlier 2.x versions held access in Keycloak's Authorization Services and in an `ownerGroups` chart value. Both are gone: access is [grants](./Granting-Access) and `ownerGroups` no longer exists. The realm migration moves existing accounts into the role groups on upgrade.
