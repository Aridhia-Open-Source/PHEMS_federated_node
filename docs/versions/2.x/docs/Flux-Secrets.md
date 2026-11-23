# Flux secrets

Secrets go in the site repository encrypted with [SOPS](https://getsops.io) and an age key; Flux decrypts them when it applies them ([ADR 0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0031-gitops-deployment-with-flux.md)). Only `data` and `stringData` are encrypted, so the rest of each Secret stays readable in review.

## The age key

1. Against the site's `kubectl` context: `mise run flux sops-key`. It makes the key if there is none and loads it into Flux as Secret `flux-system/sops-age`.
2. The private half is kept in `bootstrap/sops/age.agekey` (gitignored). Back it up: it is the only way to decrypt the site's Secrets.
3. In the site repository's `.sops.yaml`, replace `AGE_PUBLIC_KEY` with the public key it printed.
4. The Flux Kustomization needs `--decryption-provider=sops --decryption-secret=sops-age` ([Deploy with Flux](./Deploy-With-Flux), step 5).

## An encrypted Secret

1. Write the Secret like `site-example/first-user-secret.yaml`, in a file whose name matches `*secret*.yaml` (the rule in `.sops.yaml`).
2. Encrypt it in place: `sops encrypt -i my-secret.yaml`.
3. List it in `kustomization.yaml` and commit.
4. Edit it later with `sops my-secret.yaml` (needs the private key, e.g. `SOPS_AGE_KEY_FILE=bootstrap/sops/age.agekey`).

`first-user-secret.yaml` becomes `keycloak-first-user`, which the Keycloak realm controller and the `HelmRelease` read.
