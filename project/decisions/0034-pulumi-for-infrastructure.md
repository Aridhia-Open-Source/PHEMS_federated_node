# 0034. Pulumi for infrastructure

Status: Proposed, 2026-11-20.

Supersedes the OpenTofu part of [0031](0031-gitops-delivery-with-helm-and-flux.md). Flux, Helm and the site repository stay as 0031 decided.

## Context

- **We provision cloud resources only where we own the account**, Azure first: AKS, networking, Key Vault, and the identity the node uses to read secrets.
- **Sites differ.** Region, node pools, networking and identity vary per site, so the code that builds them needs real variation, not copied files.
- **The team writes Python.** [0031](0031-gitops-delivery-with-helm-and-flux.md) chose OpenTofu, which adds a second language (HCL) for the same job.

## Decision

- **Pulumi in Python provisions each site's infrastructure** where we own the account: AKS, networking, Key Vault for External Secrets, and workload identity.
- **One Pulumi stack per site.** Per-site differences are stack config and ordinary Python, not copied code.
- **Outputs feed the rest.** The stack's outputs (cluster name, Key Vault URI, identity client ids) go into the site repository and the Flux bootstrap.
- **Azure first.** AWS and GCP come later, only for sites that hand us an account.
- **Helm is never run from Pulumi.** Releases stay with Flux, as in 0031.

## Consequences

- One language across the node, the tooling and the infrastructure.
- Per-site variation is code that can be tested and reviewed.
- Pulumi state is a new thing to store, back up and protect.
- The OpenTofu code 0031 anticipated is not written.

## Alternatives considered

- **OpenTofu** (as 0031 had it): HCL is a second language, and per-site variation means modules and variable files rather than real programming.
- **Bicep or ARM templates:** Azure only, so AWS and GCP sites would need a different tool.

## Open questions

- Where Pulumi state lives: Pulumi Cloud or an Azure Blob backend.
- Who runs `pulumi up`: CI or an operator.
