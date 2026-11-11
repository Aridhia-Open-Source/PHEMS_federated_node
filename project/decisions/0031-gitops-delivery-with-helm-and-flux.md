# 0031. GitOps delivery: OpenTofu for infrastructure, Helm releases delivered by Flux

Status: Proposed, 2026-11-11.

## Context

- **Sites differ.** Nodes run on managed Kubernetes in Azure, AWS and GCP, on OpenShift, on self-hosted clusters, and on microk8s on a single VM where `helm upgrade` is run by hand.
- **There is no continuous delivery today.** Each site upgrades when someone runs a command, and nothing records what was applied or lets it be reverted.
- **Sites are locked-down networks.** Inbound access to their clusters is unlikely to be granted; outbound HTTPS usually is. Data controllers need to sign off on what reaches their node.

## Decision

- **Two layers.** OpenTofu (open-source Terraform) builds infrastructure only where we own it, Azure first: AKS, network, Key Vault, storage, DNS. Existing resources are brought in with `import` blocks or referenced with `data` sources. Sites that give us a cluster or a VM need no OpenTofu. Helm is never run from OpenTofu: no `helm_release`.
- **Releases.** GitHub Actions builds, tests and publishes the chart and the images as versioned OCI artifacts.
- **Delivery is by Flux, running in each site's cluster.** Flux pulls, so nothing needs inbound access. Flux was chosen over Argo CD because it runs real Helm releases (`helm history` and `helm rollback` still work), it is light, it fits one cluster per site, and it has no web UI to expose. Argo CD suits one central server managing many clusters, which we will not run.
- **No assumptions about the site beyond Kubernetes and outbound HTTPS.** Flux is a few controllers inside the site's own cluster, wherever that is: managed Kubernetes, OpenShift, a self-hosted cluster, or microk8s on a VM. It pulls releases out; nothing reaches into the site's network. Where a site cannot or will not run Flux, the same versioned release is applied by hand (see the fallback below).
- **A site-owned repository** holds the Flux setup, a `HelmRelease` that pins the chart version, the site's values, and the OpenTofu code if used. We have read-only access or none.
  - Secrets are never in plain text: they are SOPS-encrypted, or pulled from Key Vault by External Secrets.
  - Renovate opens version-bump pull requests. The client merging one is their sign-off.
- **Rollback.**
  - A failed upgrade is rolled back by Flux automatically.
  - A bad change that succeeded is reverted with `git revert`, and Flux upgrades back.
  - In an emergency: `flux suspend hr`, `helm rollback`, fix git, `flux resume`.
  - Reverting the chart does not undo database migrations. Migrations must stay backward compatible, or ship a down-migration.
- **Fallback for sites that cannot run Flux.** A release bundle per version: the chart, the image list or image tarballs, and an `upgrade.sh` that runs `helm upgrade --install --atomic` with the site's values. Sites whose outbound access is blocked can mirror our registry and git internally and point Flux at the mirror.
- **Node config** (git providers, repositories, projects, datasets) rides in the same Helm values. How it reaches nexus-api is decided in [0032](0032-declarative-node-config-through-an-operator.md).

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
- Reverting a release does not revert the database. Backward-compatible migrations become a rule for every change.
- OpenTofu modules for AWS and GCP come later, only for sites that hand us an account.

## Alternatives considered

- **Argo CD:** it suits one central server managing many clusters, which we will not run. For one cluster per site, Flux is lighter, has no web UI to expose, and keeps real Helm releases.
- **Helm through Terraform `helm_release`:** state drift, slow plans, and a painful rollback.
- **Push from our CI into site clusters:** needs inbound access and credentials to every site.
