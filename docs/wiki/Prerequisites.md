# Prerequisites

Before deploying the Federated Node 2.x, make sure the following are in place.


## Required tools

| Tool | Purpose | Install guide |
|---|---|---|
| `kubectl` | Interact with your Kubernetes cluster | [docs.kubernetes.io](https://kubernetes.io/docs/tasks/tools/) |
| `helm` (v3+) | Deploy the FN chart | [helm.sh/docs/intro/install](https://helm.sh/docs/intro/install/) |
| `jq` | Parse API responses in shell examples | [stedolan.github.io/jq](https://stedolan.github.io/jq/download/) |

An example `values.yaml` is in [Deploy: Core](./Deploy-Core).


## Required infrastructure

### Kubernetes cluster

Any CNCF-conformant Kubernetes cluster works. The FN is tested on:

- Azure Kubernetes Service (AKS)
- AWS Elastic Kubernetes Service (EKS)
- Google Kubernetes Engine (GKE)
- On-premises (RKE2)

Size the cluster for the base pods plus your analytics task pods. A baseline of 4 vCPU / 8 GB RAM per node worked for 1.x, and Dagster adds to it, so start larger.

The cluster's network plugin (CNI) must **enforce NetworkPolicy**: Calico, Cilium, or your cloud's network policy add-on. The chart denies a task pod all traffic except DNS and its dataset database. On a CNI that ignores NetworkPolicy, that rule does nothing.

### PostgreSQL

The FN needs a PostgreSQL server that the cluster can reach, with an admin login. It needs its own databases on it (nexus-api, Keycloak and Dagster), not your research data. By default the chart creates them for you.

If a DBA owns the databases and you have no admin login, the chart can instead use roles and databases that already exist. [Deploy: Core](./Deploy-Core#databases) covers both.

### Shared storage

Task pods and Dagster's run pods write results to the same volume, so it must be **ReadWriteMany**. ReadWriteOnce disks do not work. Supported backends:

- **Azure Files** - for AKS
- **AWS EFS** - for EKS
- **NFS** - cloud-agnostic, on-prem friendly
- **Local host path** - single node and development only

### A hostname and a certificate

The node needs a DNS name, and a TLS certificate for it (or cert-manager to get one).

### A git host and two repositories

Tasks are asked for through git, so every project needs a **trigger repository** and a **results repository**. They can be the same repository, as long as the directories used for each do not overlap. They must already exist: the node does not create them. Use either:

- **GitHub**, with a GitHub App installed on the repositories (read and write on Contents and Pull requests).
- **Gitea**, with an OAuth2 application for the admin user.

### Network access

Outbound HTTPS to `ghcr.io` (images), to your git host (`api.github.com` for GitHub), and to wherever your analytics images live. Nothing needs to call into the node to start a task.


## Install the Gateway API and Traefik CRDs

If you use the chart's Traefik (`traefik.enabled: true`, recommended for production), two sets of Kubernetes CRDs must exist before `helm install`. The chart refuses to install without them, and says so. This is a one-time step per cluster. From a checkout of the [repository](https://github.com/Aridhia-Open-Source/PHEMS_federated_node):

```sh
./scripts/gateway-api-installer.sh
```

It applies the Gateway API CRDs (version 1.4.0 unless you pass another) and the Traefik CRDs, with server-side apply. Skip this only if you set `traefik.enabled: false` and bring your own ingress.


## Notes on secrets

Credentials are Kubernetes secrets, not values in your `values.yaml`. The chart creates most of them (database passwords, Keycloak credentials, the Dagster login). [Deploy: Core](./Deploy-Core#3-create-the-namespace-and-the-secrets-you-must-provide) lists the few you have to create.

A few characters cause problems in shell `--from-literal` commands: `"` must be escaped as `\"`, and `%` needs special handling. When in doubt, use a YAML manifest and pre-encode the value with `echo -n "yourvalue" | base64`.

Create the namespace before the secrets. Secrets created in the wrong namespace are not visible to the FN pods:

```sh
kubectl create namespace federated-node
```

Git and dataset credentials are not Helm secrets. You register them through the API after the install, as global secrets.


## Next step

Follow [Deploy: Core](./Deploy-Core). The platform guides for [Azure](./1.x-Deploy-Azure), [AWS](./1.x-Deploy-AWS), [GCP](./1.x-Deploy-GCP) and [On-Premises](./1.x-Deploy-On-Premises) were written for 1.x and have not been checked for 2.x.
