# Prerequisites

Before deploying the Federated Node 2.x, make sure the following are in place.


## Required tools

| Tool | Purpose | Install guide |
|---|---|---|
| `kubectl` | Interact with your Kubernetes cluster | [docs.kubernetes.io](https://kubernetes.io/docs/tasks/tools/) |
| `helm` (v3+) | Deploy the FN chart | [helm.sh/docs/intro/install](https://helm.sh/docs/intro/install/) |
| `jq` | Parse API responses in shell examples | [stedolan.github.io/jq](https://stedolan.github.io/jq/download/) |

An example `values.yaml` is in [Deploy: Core](./Deploy-Core), and the platform guides add the storage, ingress and certificate settings for each platform.


## Required infrastructure

### Kubernetes cluster

Any CNCF-conformant Kubernetes cluster works. Each platform has its own guide with its prerequisites and known issues:

- [Azure Kubernetes Service (AKS)](./Deploy-Azure)
- [AWS Elastic Kubernetes Service (EKS)](./Deploy-AWS)
- [Google Kubernetes Engine (GKE)](./Deploy-GCP)
- [On-premises (RKE2, k3s, kubeadm)](./Deploy-On-Premises)

Size the cluster for the base pods plus your analytics task pods. Start with 4 vCPU and 8 GB RAM per node. A task pod gets 500m CPU and 1 GiB of memory by default and may use up to 2 CPU and 4 GiB, and a task spec may ask for up to 4 CPU and 16 GiB. These are `taskCompute.default` and `taskCompute.max`, so size your nodes for the number of tasks you expect to run at once.

The cluster's network plugin (CNI) must **enforce NetworkPolicy**: Calico, Cilium, or your cloud's network policy add-on. The chart denies a task pod all traffic except cluster DNS, the private address ranges in `taskNetworkPolicy.privateEgress` and the dataset databases you list in `taskNetworkPolicy.datasetEgress`. On a CNI that ignores NetworkPolicy, that rule does nothing.

### PostgreSQL

The FN needs a PostgreSQL server that the cluster can reach, with an admin login. It needs its own databases on it (`backend`, `keycloak_db` and `dagster`), not your research data. By default the chart creates them and their roles for you, and the backend creates its tables when it first starts.

Have ready the hostname, the port, and the admin login and password. On a managed service (Azure, RDS, Cloud SQL) the admin is not called `postgres`: you set it in `db.superuser`. If the server requires TLS, set `db.enforceSSL`.

If a DBA owns the databases and you have no admin login, the chart can instead use roles and databases that already exist. [Deploy: Core](./Deploy-Core#databases) covers both.

Back up Keycloak's database as well as the backend's. They are separate databases on the same server. Restoring only the backend's gives you a node that knows its datasets and projects but has lost every login.

### Shared storage

Task pods and Dagster's run pods write results to the same volume, so it must be **ReadWriteMany**. ReadWriteOnce disks do not work. Supported backends:

- **Azure Files** - for AKS
- **AWS EFS** - for EKS (the EFS CSI driver and an access point are needed)
- **NFS** - cloud-agnostic, on-prem friendly. On GKE, use Filestore
- **Local host path** - single node and development only

The choice is made at install time and is awkward to change later, because it means recreating the volumes. The per-run result folders are not removed after delivery, so size the volume for the output of every run you expect to keep.

### A hostname and a certificate

The node needs a DNS name pointing at Traefik, and a TLS certificate for it. Either create the certificate yourself, or have cert-manager get and renew one. The chart's own cert-manager issuer covers Azure DNS and Route 53. Your platform guide says what to do elsewhere.

### A git host and two repositories

Tasks are asked for through git, so every project needs a **trigger repository** and a **results repository**. They can be the same repository, as long as the directories used for each do not overlap. They must already exist: the node does not create them. Use either:

- **GitHub**, with an access token for each repository: read access for the trigger repository, and write access to Contents and Pull requests for the results repository.
- **Gitea**, with an access token for each repository (`read:repository` for the trigger, `write:repository` for the results).

### Network access

Outbound HTTPS to `ghcr.io` (images), to your git host (`api.github.com` for GitHub), and to wherever your analytics images live. If the cluster has no internet egress, mirror the FN images and your analytics images into an internal registry.

Nothing needs to call into the node to start a task. Admins who use the API reach the backend over HTTPS through Traefik, so one address must be reachable from their workstations or VPN.


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

Follow [Deploy: Core](./Deploy-Core), which covers the steps common to every platform, and add the guide for your platform alongside it:

- [Deploy: Azure (AKS)](./Deploy-Azure)
- [Deploy: AWS (EKS)](./Deploy-AWS)
- [Deploy: GCP (GKE)](./Deploy-GCP)
- [Deploy: On-Premises](./Deploy-On-Premises)
