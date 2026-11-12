# Deploy: GCP (GKE)

Not yet tested on GCP. The values below were checked against the chart's schema and render cleanly with `helm template`, but nobody has run them on GKE.

Work through [Deploy: Core](./Deploy-Core) alongside this page. The chart has **no GKE-specific settings**: it has no `on_gke` flag, no Cloud Storage backend and no Cloud DNS certificate issuer. On GKE you use the generic parts: NFS storage (Filestore), your own certificate or your own cert-manager, and the chart's Traefik.

Not yet supported in the chart: Google Cloud Storage (GCS FUSE) as the results volume, and automatic certificates through Cloud DNS. A values file with `storage.gcp` is rejected by the schema.


## Prerequisites

| You need | Why |
|---|---|
| A GKE cluster with **network policy enforcement** (Dataplane V2, or the Calico network policy add-on) | The chart denies task pods all traffic except DNS, private address ranges and the dataset databases you list. Without enforcement that rule does nothing. |
| A **Filestore** instance in the cluster's VPC | The results volume must be `ReadWriteMany`. Filestore is NFS, which the chart supports. |
| A **Cloud SQL for PostgreSQL** instance on a private IP the cluster can reach, and an admin login | Holds the FN's databases. The chart creates them for you. |
| A DNS zone you can add a record to | The node needs a hostname. |
| `kubectl` and `helm` pointed at the cluster | See [Prerequisites](./Prerequisites). |

To create a cluster with enforcement:

```sh
gcloud container clusters create <your-cluster> --region <your-region> --enable-dataplane-v2
```

Install the Gateway API and Traefik CRDs first ([Prerequisites](./Prerequisites#install-the-gateway-api-and-traefik-crds)).


## 1. Storage: Filestore over NFS

Create a Filestore instance in the same VPC and region as the cluster, and note its IP address and share name. Then use the chart's NFS backend:

```yaml
storage:
  capacity: 50Gi
  nfs:
    provisioner: nfs.csi.k8s.io
    url: 10.0.0.2           # the Filestore IP address
    path: /fnshare          # the Filestore share name, with a leading slash
```

Set `provisioner` even if you have no NFS CSI driver: the chart writes it into the StorageClass, which is invalid empty. The volume itself is a plain NFS mount.

The share must be writable. Mount it once from a VM in the same VPC and set the owner and mode, as in [Deploy: On-Premises](./Deploy-On-Premises#nfs-recommended-for-multi-node-clusters):

```sh
chown 1000:1000 /mnt/fnshare
chmod 775 /mnt/fnshare
```

Not yet supported: a Cloud Storage bucket (GCS FUSE) as the results volume.


## 2. PostgreSQL: Cloud SQL

Use the instance's **private IP**. The chart connects straight to `db.host` and `db.port`: it does not run the Cloud SQL Auth Proxy. Set `db.superuser` to the admin login you created:

```yaml
db:
  host: &dbHost 10.20.0.5
  port: 5432
  superuser: fn_admin
  enforceSSL: true
  secret:
    name: postgres-superuser
    key: password

dagster:
  enabled: true
  postgresql:
    postgresqlHost: *dbHost
    postgresqlParams:
      sslmode: require
```

Create the `postgres-superuser` secret as in [Deploy: Core](./Deploy-Core#3-create-the-namespace-and-the-secrets-you-must-provide). If a DBA owns the databases and you have no admin login, see [Deploy: Core](./Deploy-Core#databases).


## 3. Ingress and DNS

Use the chart's Traefik (`traefik.enabled: true`). GKE gives its `LoadBalancer` service an external IP. Add a DNS `A` record for your `host` pointing at it:

```sh
kubectl get svc -n federated-node -l app.kubernetes.io/name=traefik
```


## 4. TLS

**Bring your own certificate.** Create the `tls` secret from [Deploy: Core](./Deploy-Core#3-create-the-namespace-and-the-secrets-you-must-provide) and set `tls.secretName`. Nothing else is needed.

**Automatic renewal with your own cert-manager and Cloud DNS.** Do **not** set `cert-manager.enabled: true` in the FN values. The chart only builds an issuer for AKS and EKS, so on GKE it renders a ClusterIssuer with an empty `spec` and no certificate is ever issued. Instead, run cert-manager yourself and have it write the secret that `tls.secretName` names.

The steps below use Workload Identity, so no service account key is created or stored.

*Enable Workload Identity.* On the cluster and on each node pool:

```sh
gcloud container clusters update <your-cluster> \
    --workload-pool=<your-gcp-project>.svc.id.goog \
    --region <your-region>

gcloud container node-pools update <your-node-pool> \
    --cluster <your-cluster> --region <your-region> \
    --workload-metadata=GKE_METADATA
```

Check an existing cluster first: `gcloud container clusters describe <your-cluster> --region <your-region> --format="value(workloadIdentityConfig.workloadPool)"` returns `<your-gcp-project>.svc.id.goog` when it is on, and the node pool returns `GKE_METADATA` for `config.workloadMetadataConfig.mode`. Both updates take several minutes to roll out.

*Create a service account with DNS access:*

```sh
gcloud iam service-accounts create cert-manager-dns --display-name "cert-manager Cloud DNS"

gcloud projects add-iam-policy-binding <your-gcp-project> \
    --member "serviceAccount:cert-manager-dns@<your-gcp-project>.iam.gserviceaccount.com" \
    --role "roles/dns.admin"
```

*Let cert-manager's Kubernetes service account use it.* The Kubernetes service account is `<namespace>/<name>` of the one your cert-manager install runs as (`cert-manager/cert-manager` for the upstream chart's defaults):

```sh
gcloud iam service-accounts add-iam-policy-binding \
    cert-manager-dns@<your-gcp-project>.iam.gserviceaccount.com \
    --role roles/iam.workloadIdentityUser \
    --member "serviceAccount:<your-gcp-project>.svc.id.goog[cert-manager/cert-manager]"
```

Annotate that service account with `iam.gke.io/gcp-service-account: cert-manager-dns@<your-gcp-project>.iam.gserviceaccount.com`, for example with the cert-manager chart value `serviceAccount.annotations`.

*Create the issuer and the certificate.* Apply these after the FN namespace exists. The certificate writes the secret the Gateway reads:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-clouddns
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@your-institution.example.com
    privateKeySecretRef:
      name: letsencrypt-clouddns-key
    solvers:
      - dns01:
          cloudDNS:
            project: <your-gcp-project>
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: www
  namespace: federated-node
spec:
  secretName: tls
  dnsNames:
    - fn.your-institution.example.com
  issuerRef:
    name: letsencrypt-clouddns
    kind: ClusterIssuer
```


## 5. Add the GCP settings to values.yaml

On top of the file from [Deploy: Core](./Deploy-Core#4-write-your-values-file), the storage block is the Filestore one above. Nothing else is GKE-specific:

```yaml
storage:
  capacity: 50Gi
  nfs:
    provisioner: nfs.csi.k8s.io
    url: 10.0.0.2
    path: /fnshare

traefik:
  enabled: true

tls:
  secretName: tls
```

Do not add `on_gke`, `storage.gcp` or `certs.gcp`. The schema rejects `storage.gcp`, and the other two do nothing.


## Known issues

- **No Cloud Storage volume and no Cloud DNS issuer in the chart.** Use Filestore and your own cert-manager, as above.
- **`cert-manager.enabled: true` breaks certificates on GKE.** The ClusterIssuer it renders has an empty `spec`. Run cert-manager yourself.
- **Pods stuck in `ContainerCreating` with an NFS mount error.** Filestore must be in the same VPC as the cluster, and the nodes must reach it. Check the IP and share name.
- **Cloud SQL connections time out.** Use the instance's private IP, in the same VPC as the cluster or one peered with it.
- **A dataset on a public address is blocked by default.** The task network policy only allows private address ranges. List it in `taskNetworkPolicy.datasetEgress` ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)).
- **Traefik cannot read its routes.** If the cluster's API server is on a public address, add that address to `taskNetworkPolicy.privateEgress` ([Deploy: Core](./Deploy-Core#7-cluster-hardening)).


## Next step

[Post-deploy testing](./Post-Deploy-Testing)
