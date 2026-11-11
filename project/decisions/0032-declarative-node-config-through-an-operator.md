# 0032. Node config as custom resources, applied by an operator

Status: Proposed, 2026-11-11.

## Context

- **Node config today is fncli bootstrap files.** Git providers, repositories, secret references, projects and datasets are applied by fncli from files ([0025](0025-fncli-bootstrap-files-diff-apply-delete.md)).
- **Apply is additive and cannot remove.** What a file no longer lists stays in nexus-api ([0026](0026-apply-is-additive-delete-is-a-soft-delete.md)), so a revert commit cannot undo an added project.
- **Delivery is by Flux** ([0031](0031-gitops-delivery-with-helm-and-flux.md)), and a revert there should put config back as well as the chart.

## Decision

- **Node config becomes custom resources.** CRDs: `GitProvider`, `Secret` (a reference only, never the value), `Repository`, `Project`, `Dataset`. The site's Helm values list them and the chart templates them into custom resources.
- **An operator applies them.** It is written in Python with Kopf, and reuses fncli's nexus-api calls to sync each resource: create, update and, when one is removed, a soft delete under the rules of [0026](0026-apply-is-additive-delete-is-a-soft-delete.md), never `?force=true`.
- **Removal and drift.** Removing a project from the values and upgrading deletes it, so a revert works for config as it does for the chart. Drift from edits made in the UI is corrected.
- **This replaces** the "prune with `state: absent`" idea in 0026 and fncli's apply engine.
- **The operator's scope is nexus-api only.** It never touches the git server: no repository creation, no Gitea OAuth apps. Those stay dev-only fncli steps, or a one-time job run by the client.
- **CRDs ship as chart templates** (or a small separate chart), because Helm installs files in `crds/` but never upgrades them.
- **fncli keeps the bootstrap file format**, which becomes the custom resource spec and the values schema. `fncli apply`, `diff` and `delete` write, diff (with `kubectl diff`) and delete the custom resources in dev, so dev uses the operator path too.
- **fncli keeps the non-config work:** `trigger`, `demo`, `delete-gitea-token`, and the Gitea repository and OAuth setup.

## Examples

### Today: fncli bootstrap files

fncli sets up a node from YAML files, the way `kubectl apply` does for Kubernetes. The files describe the node; fncli works out what differs on the node and makes the changes.

- `bootstrap/context.yaml`: which node and cluster fncli talks to, and the default project.
- A globals file: the shared pieces, meaning git providers, repositories and their credentials. It never holds a secret value, only where to read it from.
- A project file: a project and what it is assigned (datasets, the trigger repository it watches, the results repository).

A globals file:

```yaml
version: 1
providers:
  - type: github
    uri: https://github.com
secrets:
  analysis-repo-creds:                    # a GitHub App, shared by both repositories
    values:
      APP_ID:          {env: GH_APP_ID}
      INSTALLATION_ID: {env: GH_INSTALLATION_ID}
      PRIVATE_KEY:     {file: ~/.config/fn/analysis-app.private-key.pem}
repositories:
  triggers:
    - uri: https://github.com/example-org/analysis-requests
      secret: analysis-repo-creds
  results:
    - uri: https://github.com/example-org/analysis-results
      secret: analysis-repo-creds
```

A project file:

```yaml
version: 1
projects:
  - name: cohort-study
    datasets: [omop-cdm]
    repositories:
      triggers:
        - repository: https://github.com/example-org/analysis-requests
          watch_dir: specs/
          base_branch: main
      results:
        repository: https://github.com/example-org/analysis-results
        target_dir: results/
        base_branch: main
```

Usage, from an empty node to a results pull request:

```bash
fncli diff   -f globals.yaml                  # preview: what would be created or changed
fncli apply  -f globals.yaml                  # provider, repositories, credentials
fncli apply  -f projects/cohort-study.yaml    # the project and its assignments
fncli demo   -f projects/cohort-study.yaml    # pull request -> task -> results pull request
fncli delete -f projects/cohort-study.yaml    # soft delete; skips what another project still uses
```

Taking `cohort-study` out of the file and running `apply` again changes nothing on the node ([0026](0026-apply-is-additive-delete-is-a-soft-delete.md)). That is the gap this ADR closes.

### With the operator: the same config in the site's Helm values

The site repository ([0031](0031-gitops-delivery-with-helm-and-flux.md)) holds the values. The shape is the bootstrap file's; only the secret sources change, from local env and files to Kubernetes Secrets (which SOPS or External Secrets fill).

```yaml
nodeConfig:
  providers:
    - name: github
      type: github
      uri: https://github.com
  secrets:
    analysis-repo-creds:
      fromSecret: {name: analysis-github-app}   # keys APP_ID, INSTALLATION_ID, PRIVATE_KEY
  repositories:
    triggers:
      - uri: https://github.com/example-org/analysis-requests
        secret: analysis-repo-creds
    results:
      - uri: https://github.com/example-org/analysis-results
        secret: analysis-repo-creds
  projects:
    - name: cohort-study
      datasets: [omop-cdm]
      repositories:
        triggers:
          - repository: https://github.com/example-org/analysis-requests
            watch_dir: specs/
            base_branch: main
        results:
          repository: https://github.com/example-org/analysis-results
          target_dir: results/
          base_branch: main
```

The chart turns each entry into a custom resource, for example:

```yaml
apiVersion: fn.aridhia.com/v1alpha1
kind: Project
metadata:
  name: cohort-study
spec:
  datasets: [omop-cdm]
  repositories:
    triggers:
      - repository: https://github.com/example-org/analysis-requests
        watchDir: specs/
        baseBranch: main
    results:
      repository: https://github.com/example-org/analysis-results
      targetDir: results/
      baseBranch: main
status:
  synced: true
  nexusId: 12
  message: ""
```

Usage:

- **Add or change:** edit the values, open a pull request, merge. Flux runs `helm upgrade`; the operator creates or updates the record in nexus-api.
- **Remove:** delete the entry, or `git revert` the commit that added it. Helm deletes the `Project`; the operator soft-deletes it in nexus-api.
- **See the state:** `kubectl get projects,repositories,datasets -n fn` shows each resource and whether it is synced, with the operator's message when it is not.
- **Without Flux:** `helm upgrade --install` with the same values has the same effect.
- **In dev:** `fncli apply -f projects/cohort-study.yaml` writes the same custom resources to the dev cluster, and `fncli diff` runs `kubectl diff` on them. `fncli demo` and `fncli trigger` are unchanged.

## Consequences

- A config revert works like a chart revert: through Flux, or by hand with `helm rollback`.
- Dev exercises the same operator path as production.
- The operator is a new component to build, test and run in every node.
- The fncli apply engine and its prune plans are no longer needed.
- Secrets stay out of the custom resources: a `Secret` names where the value lives.

## Alternatives considered

- **`fncli apply --prune` run as a Flux Job**, with ownership tags or a state ConfigMap: a second engine, Job plumbing, and prune and ownership logic built by hand where the operator path gets them from Flux and Kubernetes.
- **Crossplane:** needs a nexus-api provider, which is the same effort as our own operator, and it is heavier to run.
- **An operator that also creates git repositories and OAuth apps:** not needed in production, and the hardest part to get right.

Delivery of the chart and the operator itself is covered in [0031](0031-gitops-delivery-with-helm-and-flux.md).
