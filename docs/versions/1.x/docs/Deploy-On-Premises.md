# Deploy: On-Premises

Work through [Deploy: Core](Deploy-Core.md) alongside this guide.

This guide covers production on-premises deployments using distributions commonly used in healthcare and enterprise environments. Local single-node setups (e.g. for development) are covered briefly at the end.


## Choosing a distribution

The FN has been tested on **RKE2** and that is the recommended distribution for on-premises deployments. It is hardened by default (CIS benchmark), uses containerd, and is well suited to healthcare and regulated environments.

Other CNCF-conformant distributions - including k3s and kubeadm - should work given the FN has no hard dependency on any specific distribution, but these have not been formally tested. The steps in this guide are written for RKE2 and note where behaviour may differ on other distributions.


## Before you start

Complete [Prerequisites](Prerequisites.md), including the **Gateway API and Traefik CRD pre-install step** - this is required before `helm install` if you are using Traefik as your ingress.


## Storage

The FN requires a `ReadWriteMany` persistent volume for task results. The chart creates its own StorageClass (`federatednode-shared-results`) and PersistentVolume. You configure which backend that volume uses.

### NFS (recommended for multi-node production clusters)

NFS is the most practical `ReadWriteMany` solution for on-premises multi-node clusters. Any node in the cluster can read and write results without pod scheduling constraints.

**Prerequisites:**

- An NFS server accessible from all cluster nodes (a dedicated NAS, a standalone Linux host, or existing storage infrastructure)

Ensure the export directory on your NFS server is writable by the FN pods, which run as non-root UID 1000:

```sh
mkdir -p /exports/federated-node
chown 1000:1000 /exports/federated-node
chmod 775 /exports/federated-node
```

**Add to values.yaml:**

```yaml
storage:
  capacity: 50Gi
  nfs:
    url: 192.168.1.100            # your NFS server IP or hostname
    path: /exports/federated-node # exported path on the NFS server
```

> **Optional:** If you have [csi-driver-nfs](https://github.com/kubernetes-csi/csi-driver-nfs) installed, you can set `storage.nfs.provisioner: nfs.csi.k8s.io` to use it as the StorageClass provisioner label. It is not required - the NFS mount works without it.

### Local host path (single-node or development only)

Local path storage pins task pods to the node that holds the data. This is fine for single-node clusters or development, but not suitable for multi-node production - if the pod is scheduled on a different node it won't find its volume.

Create the directory, ensuring the FN's non-root user (UID 1000) can write to it:

```sh
mkdir -p /data/federated-node/results
chown 1000:1000 /data/federated-node/results
```

**Add to values.yaml:**

```yaml
storage:
  capacity: 50Gi
  local:
    path: /data/federated-node/results
```


## Ingress

The FN uses Traefik with the Kubernetes Gateway API. The chart bundles Traefik as a subchart - you do not need to install it separately, and you do not need to remove or disable any existing ingress controller on your cluster.

### Coexistence with existing ingress controllers

RKE2 and k3s both ship with their own bundled Traefik instance. The FN's Traefik can run alongside it without conflict. The two instances are isolated by design:

- RKE2/k3s's Traefik registers as IngressClass `traefik` and watches standard `Ingress` resources
- The FN's Traefik registers its own GatewayClass (`traefik-fn-gateway-class`) and only watches `Gateway` and `HTTPRoute` resources that reference that class

They route completely independently and neither will interfere with the other's traffic.

The one practical consideration is **port exposure**: if your existing ingress controller already claims port 443 on all nodes, you need to expose the FN's Traefik on a different address - either via a separate IP (MetalLB pool, floating IP), a different NodePort, or behind your existing load balancer as a named virtual host. See the [Exposing Traefik](#exposing-traefik-to-your-network) section below.

### kubeadm

No bundled ingress. Install the Gateway API and Traefik CRDs (see [Prerequisites](Prerequisites.md)) and set `traefik.enabled: true` in your values.


## Exposing Traefik to your network

Traefik listens internally on port **8443** (HTTPS) and **8000** (HTTP). You need to make port 443 accessible to users. The right approach depends on your infrastructure.

### Using a hardware or software load balancer (recommended)

If your environment has an existing load balancer (F5, HAProxy, nginx, MetalLB), configure it to forward port 443 to the Traefik service's NodePort or ClusterIP.

**[MetalLB](https://metallb.universe.tf)** is a common choice for on-premises Kubernetes - it gives Traefik a real external IP from your network's address range without needing cloud infrastructure. Follow the [MetalLB installation guide](https://metallb.universe.tf/installation/) to set it up, then once Traefik has claimed an IP, add that to your DNS for the `host` value in your FN values.

If you want to lock Traefik to a specific IP rather than letting MetalLB assign one, set it explicitly:

```yaml
traefik:
  enabled: true
  service:
    spec:
      externalIPs:
        - 192.168.1.200
```

### Using NodePort with an external reverse proxy

If you cannot run MetalLB, expose Traefik as a NodePort and point an existing reverse proxy (nginx, HAProxy) at it:

```yaml
traefik:
  enabled: true
  service:
    type: NodePort
```

Then configure your reverse proxy to forward `443 -> <any-node-ip>:<traefik-nodeport>`.


## TLS

### With cert-manager (recommended if you have a public or ACME-compatible CA)

cert-manager automates certificate renewal. Install it via the FN chart itself:

```yaml
cert-manager:
  enabled: true
  installCRDs: true
```

For internal CA or Let's Encrypt with DNS-01 challenge, configure a ClusterIssuer after deployment. The FN chart's built-in issuer uses Let's Encrypt with DNS-01 (Azure or AWS DNS). For other DNS providers, install cert-manager separately and manage the ClusterIssuer manually, pointing it at your CA.

### With an existing certificate

If your institution has a PKI or provides certificates from an internal CA:

```sh
kubectl create secret tls tls \
    --key server.key \
    --cert server.crt \
    -n federated-node
```

Reference it in values:

```yaml
tls:
  secretName: tls
```

The certificate's CN or SAN must match your `host` value. Intermediate certificates should be bundled into `server.crt` (full chain).

### Self-signed (internal/development only)

```sh
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout server.key \
  -out server.crt \
  -subj "/CN=fn.your-institution.internal"

kubectl create secret tls tls \
    --key server.key \
    --cert server.crt \
    -n federated-node
```

Clients will need to trust your CA or accept the self-signed cert.


## PostgreSQL

Provide an external PostgreSQL instance. Options commonly used on-prem:

- **CloudNativePG** or **Zalando Postgres Operator** - run a managed PostgreSQL cluster inside Kubernetes
- **Standalone PostgreSQL** on a VM or bare-metal host outside the cluster
- **Patroni** - for HA PostgreSQL

The FN does not need a dedicated server - a shared PostgreSQL instance with a dedicated database and user is sufficient. The FN creates its own schema on first boot.

Minimum: PostgreSQL 12, 1 vCPU, 2 GB RAM for the FN's own metadata database.


## Pod security

The FN pods run non-root (`runAsNonRoot: true`, UID 1000) with `allowPrivilegeEscalation: false`, all Linux capabilities dropped, and `seccompProfile: RuntimeDefault`. This is compatible with:

- RKE2's default Pod Security Standards (`restricted` or `baseline` namespace labels)
- CIS-hardened cluster profiles

If your cluster enforces `restricted` Pod Security Standards, label the FN namespaces accordingly:

```sh
kubectl label namespace federated-node \
  pod-security.kubernetes.io/enforce=restricted

kubectl label namespace keycloak \
  pod-security.kubernetes.io/enforce=restricted

kubectl label namespace tasks \
  pod-security.kubernetes.io/enforce=baseline
```

The `tasks` namespace runs analytics containers whose security posture depends on the images your researchers provide - use `baseline` there unless you control all analytics images.

The chart also creates a `ClusterRole` giving the backend service account broad permissions over pods, PVs, PVCs, jobs, and secrets (needed to dynamically create per-task storage and run task pods). This is expected behaviour - ensure your cluster's RBAC policies permit ClusterRole creation by the deploying user.


## Complete values.yaml example (RKE2, NFS, MetalLB)

```yaml
host: fn.your-institution.internal

db:
  host: postgres.db.svc.cluster.local   # or external PostgreSQL host
  name: federated_node_db
  port: 5432
  user: fn_user
  secret:
    name: fn-db-secret
    key: value

firstUserSecret:
  name: fn-first-user
  passKey: password
  email: admin@your-institution.example.com
  firstName: Admin
  lastName: User

storage:
  capacity: 50Gi
  nfs:
    provisioner: nfs-client
    url: 192.168.1.100
    path: /exports/federated-node

traefik:
  enabled: true
  service:
    spec:
      externalIPs:
        - 192.168.1.200   # MetalLB or static IP

tls:
  secretName: tls   # pre-created TLS secret

keycloak:
  replicas: 2

cleanupTime: 7

integrations:
  domains:
    - https://fn.your-institution.internal
```


## Networking checklist

Before deploying, confirm:

- [ ] Cluster nodes can reach your PostgreSQL host on port 5432
- [ ] Cluster nodes can reach your NFS server on the NFS port (2049)
- [ ] Cluster nodes can reach container registries (ghcr.io, and wherever your analytics images are hosted)
- [ ] The Traefik external IP or NodePort is reachable from researcher workstations
- [ ] If using the Task Controller: cluster nodes have outbound HTTPS access to github.com
- [ ] If using cert-manager with DNS-01: cluster nodes can reach your DNS provider's API


## Deploy

Return to [Deploy: Core](Deploy-Core.md) step 8 and run `helm install` with your completed `values.yaml`.


## Next step

[Post-Deploy Testing](Post-Deploy-Testing.md)
