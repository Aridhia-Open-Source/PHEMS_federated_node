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
