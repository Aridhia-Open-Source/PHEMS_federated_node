# Authentication

The node uses OpenID Connect (OIDC) for authentication. The chart ships Keycloak, and Keycloak can federate sign-in to an institution's directory or another identity provider. nexus-api verifies signed access tokens locally and uses the token's stable subject, node role and groups when applying its access rules.

Authentication and authorization are separate:

- Keycloak proves who the caller is and supplies claims.
- nexus-api loads the record and decides whether the requested operation is allowed. Keycloak does not hold a policy or permission for each dataset.

## Accounts and roles

Each account has exactly one node role. The built-in roles are:

| Role | Use |
|---|---|
| `SuperUser` | break-glass recovery; bypasses grants but not application state rules |
| `Administrator` | node setup and global resource administration |
| `Service` | the operator's client-credentials account |
| `Users` | normal researcher access through grants |
| `Dagster` | the pipeline client on its documented routes |

Role membership is represented by Keycloak groups (`/roles/admins`, `/roles/users`, and so on), so a site can map directory groups into the node realm. The first user is an `Administrator`. The operator and Dagster use confidential clients and client credentials; they do not use a person's password.

`SuperUser` is for recovery, not daily work. It can claim or reassign records and operate without a grant, but revoked resources and invalid state transitions still fail. Keep its credentials in the Kubernetes Secret named by the chart values.

## Tokens and sign-in

nexus-api checks the issuer, signature, expiry and the node role locally. It reads only:

```json
{
  "sub": "stable-account-id",
  "realm_access": { "roles": ["Users"] },
  "groups": ["/roles/users", "/studies/example"]
}
```

Keycloak's built-in roles are ignored. A token with no node role, or with more than one node role, is rejected. `/login` accepts form fields and returns an access token (and refresh token) for interactive users:

```bash
curl -sS -X POST https://<host>/login \
  -F 'username=<email>' -F 'password=<password>'
```

Programs should use their client id and secret, then send `Authorization: Bearer <access-token>` to nexus-api. Refresh tokens go only to Keycloak. If the identity provider is unavailable, existing tokens can still be verified; only sign-in or token refresh is affected.

## Deployment checklist

1. Set the realm name and the public issuer address consistently in the chart values.
2. Provide the first administrator Secret; do not put its password in values or git.
3. Protect the generated or supplied Keycloak, operator and Dagster client credentials.
4. Check that the `keycloak-realm-init` job completed and that `/health_check` returns `status: ok`.
5. If using an external identity provider, set `keycloak.allowExternalEgress: true` and configure its trust chain as described in [Deploy: Core](Deploy-Core.md).

The role and system-account model is specified in [ADR 0036](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0036-keycloak-authentication-roles-and-system-accounts.md); the provider boundary is in [ADR 0035](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0035-api-authorization-oidc-authentication.md). For chart secret names and rotation, see the [chart README](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/k8s/federated-node/README.md).
