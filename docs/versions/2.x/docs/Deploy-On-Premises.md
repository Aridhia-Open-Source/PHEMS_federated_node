# Deploy on-premises (UNTESTED)

Work through [Deploy: Core](./Deploy-Core) alongside this page. It covers production on-premises deployments on distributions common in healthcare and enterprise environments. A local single-node setup is covered under [Local host path](#local-host-path-single-node-only).


## Choosing a distribution

**RKE2** is the recommended distribution for on-premises. It is hardened by default (CIS benchmark), uses containerd, and suits regulated environments. Its default network plugin, Canal, enforces NetworkPolicy, which the chart relies on.

The steps below are written for RKE2 and say where k3s or kubeadm differ.


## Prerequisites

| You need | Why |
|---|---|
| A cluster whose network plugin **enforces NetworkPolicy** (Canal or Calico, Cilium) | The chart denies task pods all traffic except DNS, private address ranges and the dataset databases you list. A plugin that ignores NetworkPolicy makes that rule do nothing. |
| Shared storage that is **ReadWriteMany**: an NFS export, or a local path on a single node | Task pods and Dagster's run pods write results to the same volume. |
| A **PostgreSQL** server the cluster can reach, and an admin login | Holds the FN's databases. The chart creates them for you. |
| An address for Traefik that users can reach, and a DNS record for `host` | Ingress. See below. |
| A TLS certificate for `host`, from your CA | Or cert-manager that you run yourself. |
| The Gateway API and Traefik CRDs | [Prerequisites](./Prerequisites#install-the-gateway-api-and-traefik-crds). Required before `helm install` if you use the chart's Traefik. |


## Storage

The chart builds a StorageClass (`<release>-dagster-artifacts`) and a PersistentVolume for the results. You choose which backend sits behind them under `storage`.

### NFS (recommended for multi-node clusters)

NFS is the most practical `ReadWriteMany` option on-premises: any node can read and write results with no pod scheduling constraints. You need an NFS server every cluster node can reach (a NAS, a Linux host, or existing storage infrastructure).

Make the export writable by the FN's non-root user, UID 1000:

```sh
mkdir -p /exports/federated-node
chown 1000:1000 /exports/federated-node
chmod 775 /exports/federated-node
```

```yaml
storage:
  capacity: 50Gi
  nfs:
    provisioner: nfs.csi.k8s.io
    url: 192.168.1.100              # your NFS server IP or hostname
    path: /exports/federated-node   # the exported path
```

Set `provisioner` even if you have no NFS CSI driver ([csi-driver-nfs](https://github.com/kubernetes-csi/csi-driver-nfs) is one): the chart writes it into the StorageClass, which is invalid empty. The volume itself is a plain NFS mount, and is mounted `hard`.

### Local host path (single node only)

A local path pins the pods to the node that holds the data. It is fine for a single-node cluster or development, and wrong for a multi-node production cluster: a pod scheduled on another node finds no volume.

```sh
mkdir -p /data/federated-node/results
chown 1000:1000 /data/federated-node/results
```

```yaml
storage:
  capacity: 50Gi
  local:
    artifacts: /data/federated-node/results
```

`storage.local.artifacts` is the directory the results volume uses. `storage.local.dbpath` is only used when the chart runs its own development PostgreSQL.


## Ingress

The chart's Traefik uses the Kubernetes Gateway API. You do not install it separately, and you do not need to remove or disable another ingress controller on the cluster.

### Coexisting with a bundled ingress controller

RKE2 and k3s ship their own ingress controller. The FN's Traefik runs beside it without conflict, because they watch different objects:

- The bundled controller watches standard `Ingress` resources.
- The FN's Traefik registers its own GatewayClass (`traefik-fn-gateway-class`) and only watches the `Gateway` and `HTTPRoute` objects that use it.

The one thing to plan for is **port exposure**. If the bundled controller already claims port 443 on every node, give the FN's Traefik a different address: its own IP (a MetalLB pool or a floating IP), a different NodePort, or a named virtual host behind your existing load balancer.

### kubeadm

There is no bundled ingress. Install the CRDs (see Prerequisites above) and set `traefik.enabled: true`.


## Exposing Traefik

Traefik listens inside the cluster on port **8443** (HTTPS) and **8000** (HTTP). Its Service maps them to ports **443** and **80**. How users reach port 443 depends on your infrastructure.

### A load balancer (recommended)

If you have a hardware or software load balancer (F5, HAProxy, nginx, MetalLB), forward port 443 to the Traefik Service.

[MetalLB](https://metallb.universe.tf) is a common choice on-premises: it gives Traefik a real address from your network's range without any cloud infrastructure. Install it, wait until Traefik has claimed an address, and use that for the DNS record of `host`.

To fix Traefik to a known address rather than letting the load balancer pick one:

```yaml
traefik:
  enabled: true
  service:
    externalIPs:
      - 192.168.1.200
```

The key is `traefik.service.externalIPs`.

### A NodePort behind a reverse proxy

If you cannot run MetalLB, expose Traefik as a NodePort and point an existing reverse proxy (nginx, HAProxy) at it:

```yaml
traefik:
  enabled: true
  service:
    type: NodePort
```

Then forward `443` on the proxy to `<any node IP>:<Traefik NodePort>`. Find the port with `kubectl get svc -n federated-node -l app.kubernetes.io/name=traefik`.


## TLS

### An existing certificate

If your institution has a PKI or issues certificates from an internal CA:

```sh
kubectl create secret tls tls -n federated-node --key server.key --cert server.crt
```

```yaml
tls:
  secretName: tls
```

The certificate's CN or SAN must match `host`. Bundle intermediate certificates into `server.crt` (the full chain).

### Automatic renewal

The chart's own cert-manager issuer only supports Azure DNS and Route 53. For an internal CA, or Let's Encrypt with another DNS provider, run cert-manager yourself, create your own ClusterIssuer and a Certificate in the release namespace that writes the secret named by `tls.secretName`, and leave `cert-manager.enabled` off.

### Self-signed (internal or test use only)

```sh
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout server.key -out server.crt \
  -subj "/CN=fn.your-institution.internal"

kubectl create secret tls tls -n federated-node --key server.key --cert server.crt
```

Clients (browsers, `curl`, scripts) must trust your CA or accept the certificate.


## PostgreSQL

Provide the server yourself. Options in common use on-premises:

- **CloudNativePG** or the **Zalando Postgres Operator**: a managed PostgreSQL cluster inside Kubernetes.
- **Standalone PostgreSQL** on a VM or bare-metal host outside the cluster.
- **Patroni** for high availability.

The FN does not need a dedicated server. A shared one is fine: the chart creates its own databases and roles on it (`fn_nexus`, `keycloak_db` and `dagster`). The `db.superuser` login needs the right to create them. Set `db.enforceSSL: true` unless the database is on the same host, and then also set `dagster.postgresql.postgresqlParams.sslmode: require`. Size it for the FN's metadata only: 1 vCPU and 2 GB RAM is enough to start.

If a DBA owns the databases and you have no admin login, see [Deploy: Core](./Deploy-Core#databases).


## Pod security

The FN pods run non-root with `allowPrivilegeEscalation: false`, all Linux capabilities dropped and a `RuntimeDefault` seccomp profile. That fits RKE2's default Pod Security Standards and CIS-hardened profiles.

If the cluster enforces `restricted`, label the FN namespaces as in [Deploy: Core](./Deploy-Core#7-cluster-hardening). The `tasks` namespace runs whatever images researchers supply, so use `baseline` there unless you control all of them.

The chart also creates a `ClusterRole` for the backend (it creates storage and task pods for each task), so the user running `helm install` must be allowed to create cluster roles.


## DNS inside the cluster

Task pods may send DNS lookups only to the pods in `taskNetworkPolicy.dns`. The default is the pods labelled `k8s-app: kube-dns` in `kube-system`. If your distribution labels its DNS pods differently, or you run NodeLocal DNSCache, change that value or tasks cannot resolve their dataset host.


## Complete values.yaml example (RKE2, NFS, MetalLB)

```yaml
host: fn.your-institution.internal
nodeId: your-institution

db:
  host: &dbHost postgres.db.svc.cluster.local   # or your external PostgreSQL host
  port: 5432
  superuser: fn_admin
  enforceSSL: true
  secret:
    name: postgres-superuser
    key: password

firstUserSecret:
  name: fn-first-user
  passKey: password
  email: admin@your-institution.example.com
  firstName: Admin
  lastName: User

storage:
  capacity: 50Gi
  nfs:
    provisioner: nfs.csi.k8s.io
    url: 192.168.1.100
    path: /exports/federated-node

traefik:
  enabled: true
  service:
    externalIPs:
      - 192.168.1.200   # MetalLB or static address

tls:
  secretName: tls       # the pre-created TLS secret

integrations:
  domains:
    - https://fn.your-institution.internal

dagster:
  enabled: true
  postgresql:
    postgresqlHost: *dbHost
    postgresqlParams:
      sslmode: require
```


## Networking checklist

Before deploying, confirm that:

- [ ] Cluster nodes can reach PostgreSQL on port 5432.
- [ ] Cluster nodes can reach the NFS server on port 2049.
- [ ] Cluster nodes can pull from `ghcr.io` and from wherever your analytics images live.
- [ ] Cluster nodes have outbound HTTPS to your git host (`api.github.com` for GitHub).
- [ ] The Traefik address, or NodePort, is reachable from researcher and admin workstations.
- [ ] Each dataset database is reachable from the tasks namespace. The default `taskNetworkPolicy.privateEgress` covers `10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16`. A database outside those ranges needs a `taskNetworkPolicy.datasetEgress` rule ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)).
- [ ] If you use a DNS-01 certificate, the cluster can reach your DNS provider's API.


## Known issues

- **Two controllers want port 443.** On RKE2 or k3s the bundled ingress controller may already hold it. Give the FN's Traefik its own address.
- **A task cannot reach a database on an address outside the private ranges.** Add a `taskNetworkPolicy.datasetEgress` rule.
- **Pods cannot write to the NFS export.** Check ownership and mode on the export as above, and your NFS server's squash settings.


## Next step

[Post-deploy testing](./Post-Deploy-Testing)
