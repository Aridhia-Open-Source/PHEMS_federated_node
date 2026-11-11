# 0031. GitOps delivery: Helm, Flux in each site's cluster, and an operator for node config

Status: Proposed, 2026-11-11.

## Context

- **Sites differ.** GOSH (us), HUS and Erasmus are on Azure. SJD is on AWS, reached through Denodo. Later: Warsaw (self-hosted), Vienna (OpenShift), Oslo (a private cloud, not yet known) and Leuven (GCP). Some "Azure" clients really run microk8s on a single Azure VM and run `helm upgrade` by hand.
- **There is no continuous delivery today.** Node config (git providers, repositories, secret references, projects, datasets) is applied by fncli from bootstrap files ([0025](0025-fncli-bootstrap-files-diff-apply-delete.md)). Apply is additive and cannot remove what a file no longer lists ([0026](0026-apply-is-additive-delete-is-a-soft-delete.md)), so a revert commit cannot undo an added project.
- **Sites are hospital networks.** Inbound access to their clusters is unlikely to be granted; outbound HTTPS usually is. Data controllers need to sign off on what reaches their node.

## Decision

- **Two layers.** OpenTofu (open-source Terraform) builds infrastructure only where we own it, Azure first: AKS, network, Key Vault, storage, DNS. Existing resources are brought in with `import` blocks or referenced with `data` sources. Sites that give us a cluster or a VM need no OpenTofu. Helm is never run from OpenTofu: no `helm_release`.
- **Releases.** GitHub Actions builds, tests and publishes the chart and the images as versioned OCI artifacts.
- **Delivery is by Flux, running in each site's cluster.** Flux pulls, so nothing needs inbound access. Flux was chosen over Argo CD because it runs real Helm releases (`helm history` and `helm rollback` still work), it is light, it fits one cluster per site, and it has no web UI to expose. Argo CD suits one central server managing many clusters, which we will not run.
- **A client-owned site repository** holds the Flux setup, a `HelmRelease` that pins the chart version, the site's values, and the OpenTofu code if used. We have read-only access or none.
  - Secrets are never in plain text: they are SOPS-encrypted, or pulled from Key Vault by External Secrets.
  - Renovate opens version-bump pull requests. The client merging one is their sign-off.
- **Rollback.**
  - A failed upgrade is rolled back by Flux automatically.
  - A bad change that succeeded is reverted with `git revert`, and Flux upgrades back.
  - In an emergency: `flux suspend hr`, `helm rollback`, fix git, `flux resume`.
  - Reverting the chart does not undo database migrations. Migrations must stay backward compatible, or ship a down-migration.
- **Node config becomes custom resources, applied by an operator.**
  - CRDs: `GitProvider`, `Secret` (a reference only, never the value), `Repository`, `Project`, `Dataset`.
  - The site's Helm values list them and the chart templates them into custom resources.
  - An operator (Python, Kopf, reusing fncli's nexus-api client calls) syncs them to nexus-api: create, update and, when one is removed, a soft delete under the rules of [0026](0026-apply-is-additive-delete-is-a-soft-delete.md), never `?force=true`.
  - Removing a project from the values and upgrading deletes it, so a revert works for config as it does for the chart. Drift from edits made in the UI is corrected.
  - This replaces the "prune with `state: absent`" idea in 0026 and fncli's apply engine.
- **The operator's scope is nexus-api only.** It never touches the git server: no repository creation, no Gitea OAuth apps. Those stay dev-only fncli steps, or a one-time job run by the client.
- **CRDs ship as chart templates** (or a small separate chart), because Helm installs files in `crds/` but never upgrades them.
- **fncli keeps the bootstrap file format**, which becomes the custom resource spec and the values schema. `fncli apply`, `diff` and `delete` write, diff (with `kubectl diff`) and delete the custom resources in dev, so dev uses the operator path too. fncli keeps the non-config work: `trigger`, `demo`, `delete-gitea-token`, and the Gitea repository and OAuth setup.
- **Fallback for sites that cannot run Flux.** A release bundle per version: the chart, the image list or image tarballs, and an `upgrade.sh` that runs `helm upgrade --install --atomic` with the site's values. Sites whose outbound access is blocked can mirror our registry and git internally and point Flux at the mirror.

An example of what the site repository pins:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: federated-node
  namespace: federated-node
spec:
  interval: 10m
  chart:
    spec:
      chart: federated-node
      version: "1.4.0"
      sourceRef:
        kind: HelmRepository
        name: fn-charts
  upgrade:
    remediation:
      retries: 2
      strategyOnExhaustion: rollback
```

## Consequences

- Every change to a node, a version or a config change, is a reviewed commit with a history and a revert.
- microk8s-on-VM sites stop running helm by hand. They run `flux install` once.
- The same release goes everywhere, including OpenShift, AWS and GCP.
- The operator is a new component to build, test and run in every node.
- OpenTofu modules for AWS and GCP come later, only for sites that hand us an account.

## Alternatives considered

- **Argo CD:** it suits one central server managing many clusters, which we will not run. For one cluster per site, Flux is lighter, has no web UI to expose, and keeps real Helm releases.
- **Helm through Terraform `helm_release`:** state drift, slow plans, and a painful rollback.
- **Push from our CI into client clusters:** needs inbound access and credentials to every site.
- **`fncli apply --prune` run as a Flux Job**, with ownership tags or a state ConfigMap: a second engine, Job plumbing, and prune and ownership logic built by hand where the operator path gets them from Flux and Kubernetes.
- **Crossplane:** needs a nexus-api provider, which is the same effort as our own operator, and it is heavier to run.
- **An operator that also creates git repositories and OAuth apps:** not needed in production, and the hardest part to get right.
