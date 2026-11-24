# Flux secrets

A site's Secrets come from one of two places ([ADR 0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0031-gitops-deployment-with-flux.md)), each a folder in the site repository that makes the same Secrets:

- `secrets/sops` (the default): committed encrypted with [SOPS](https://getsops.io) and an age key; Flux decrypts them when it applies them.
- `secrets/vault`: kept in Azure Key Vault; the [External Secrets Operator](https://external-secrets.io) copies them into the cluster.

Switching is one line in the site's `kustomization.yaml`: `- secrets/sops` or `- secrets/vault`.

The Secrets live in the site repository, not the chart, because Flux reads `keycloak-first-user` (the first user's email, for the `HelmRelease`) before it renders the chart.

## SOPS

1. Against the site's `kubectl` context: `mise run flux sops-key`. It makes the age key if there is none and loads it into Flux as Secret `flux-system/sops-age`. The private half is kept in `bootstrap/sops/<kubectl context>.agekey` (gitignored, one file per cluster): back it up, it is the only way to decrypt the site's Secrets.
2. In the site repository's `.sops.yaml`, replace `AGE_PUBLIC_KEY` with the public key it printed.
3. The Flux Kustomization needs `--decryption-provider=sops --decryption-secret=sops-age` ([Deploy with Flux](./Deploy-With-Flux), step 5).
4. Fill in `secrets/sops/first-user-secret.yaml` and encrypt it in place: `sops encrypt -i secrets/sops/first-user-secret.yaml`. Only `data` and `stringData` are encrypted, so the rest stays readable in review.
5. Another Secret: a file in `secrets/sops` whose name matches `*secret*.yaml` (the rule in `.sops.yaml`), encrypted the same way and listed in `secrets/sops/kustomization.yaml`. Edit one later with `sops <file>` (needs the private key, e.g. `SOPS_AGE_KEY_FILE=bootstrap/sops/<kubectl context>.agekey`).

`secrets/sops/first-user-secret.yaml` makes `keycloak-first-user` in two namespaces: `keycloak` for the Keycloak realm controller, the release namespace for the `HelmRelease`'s email. The chart copies no Secret, so each goes where it is read; `namespaces.yaml` makes the namespaces first (`global.createNamespaces: false`). `secrets/vault` fills the same two.

## Vault (Azure Key Vault)

1. Install the External Secrets Operator in the cluster (its Helm chart, `external-secrets`).
2. Give a managed identity the role "Key Vault Secrets User" on the vault, and a federated credential for the cluster's OIDC issuer with subject `system:serviceaccount:fn:fn-external-secrets`.
3. In `secrets/vault/serviceaccount.yaml`, replace `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` with that identity's; in `secrets/vault/store-azure.yaml`, replace `AZURE_KEY_VAULT` with the vault's name. The store is a ClusterSecretStore, so that one identity fills every namespace.
4. Put each Secret in the vault as one entry holding its keys as JSON, named like the Secret: `az keyvault secret set --vault-name <vault> --name keycloak-first-user --value '{"EMAIL": "...", "PASSWORD": "..."}'`.
5. In the site's `kustomization.yaml`, change `- secrets/sops` to `- secrets/vault`. Commit.

On the dev cluster, `mise run openbao up` installs the operator and [OpenBao](https://openbao.org) (in memory, dev mode), writes the first user's login from `.dev.env`, and applies `secrets/vault` with `store-openbao.yaml` in place of the Azure store. `mise run openbao status` shows the entries and the ExternalSecrets; `mise run openbao down` removes them and leaves the Secrets in place.
