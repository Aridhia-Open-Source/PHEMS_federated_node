# Flux stack review (Claude)

Findings per PR. Format: file:line - issue - fix - comment.

## #691 flux deployment

- `scripts/gitea_lib.sh:42` - The site repository is created public (no `"private": true`), so any Gitea account or anonymous visitor reads the node's values and later its encrypted Secrets. - Add `"private": true` to the create body, as `mirror_to_gitea.sh` (#702) does. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/691#discussion_r4674994227

## #725 sops secrets

- `scripts/flux.sh:43` - `load_sops_key` reuses `bootstrap/sops/age.agekey` whatever the kubectl context, so `flux sops-key` against a site loads the dev key and all sites from one checkout share a private key. - One key file per context/cluster, or refuse outside the kind cluster. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/725#discussion_r4674997657
- `scripts/flux.sh:106` - Password substituted with sed: `&`, `|` or `\` in it silently change or break the committed Secret. - Fill with yq `strenv` or `kubectl create secret --dry-run`. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/725#discussion_r4674997661

## #717 remove copy-secrets

- `k8s/federated-node/templates/keycloak-namespace.yaml:3` - Existing releases own the keycloak/cert-manager namespaces (after any upgrade) and the tasks namespace with no `keep`; Helm checks keep on the live object, so a site switching straight to `createNamespaces: false` deletes them and the Secrets in them. - Two-step upgrade (one release with `true` to add keep, then `false`), documented or guarded. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/717#discussion_r4674999742
- `k8s/federated-node/values.yaml:227` - Dropping copy-secrets.yaml makes the upgrade delete the copied first-user and cert-manager Secrets, even ones pre-applied with the same name. - Document re-creating them after the upgrade, or ship copies with `keep` one release first. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/717#discussion_r4674999755

## #703 external secrets

- `site-example/secrets/vault/store-azure.yaml:7` - ClusterSecretStore with no `conditions`: an ExternalSecret in any namespace can read every Key Vault entry through the node's identity. - `spec.conditions` limited to fn and keycloak (also store-openbao.yaml), or namespaced SecretStores. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/703#discussion_r4675001430

## #702 mirror to gitea

- No findings.

## #726 site CI pipelines

- `site-example/ci/validate.sh:78` - SOPS check only covers files matching `.sops.yaml` path_regex, so a plain Secret under another file name passes CI in plain text. - Check every `kind: Secret` in the kustomize build output has `ENC[` values. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/726#discussion_r4675002948
