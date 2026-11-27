# Plan: GitHub and Flux integration (PR #779)

Status: implemented.

- Use an external Gitea site repository and Actions runner so the GitOps
  boundary is visible: a merged site pull request changes `main`, Flux
  reconciles it, and the Federated Node is installed from the resulting
  revision.
- Keep Flux responsible for the application release. `mise run flux up`
  installs Flux, configures the GitRepository and Kustomization, creates the
  SOPS key, and leaves the application absent until the installation pull
  request is merged.
- Keep `flux/examples/demo.sh` focused on setup: cluster and image
  preparation, Gitea bootstrap, installation PR, resource PR, operator
  resources, and fncli configuration. It must not create or merge the
  experiment trigger pull request.
- Keep `flux/examples/run-demo.sh` as the second, explicit command for the
  trigger PR, Dagster execution, delivery branch, and results PR.
- Use the existing operator, Keycloak, fncli, Flux, SOPS, and GitOps ADRs and
  documentation as the source of truth; update only the examples and
  integration glue required to make the documented flow reproducible.
- Validate the boundary with the setup demo, Flux resource status, HelmRelease
  reconciliation, Gitea Actions checks, operator resources, and the separate
  trigger/results flow.

