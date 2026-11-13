# Deploy on Azure (UNTESTED)

Work through [Deploy: Core](./Deploy-Core) alongside this page. The steps here are what is different on Azure: the prerequisites, the Azure Files storage, the PostgreSQL settings, ingress and DNS, and certificate renewal.


## Prerequisites

| You need | Why |
|---|---|
| An AKS cluster with a **network policy plugin** enabled (Azure, Calico or Cilium) | The chart denies task pods all traffic except DNS, private address ranges and the dataset databases you list. AKS does not enforce that without a plugin. |
| An **Azure Storage account with a file share** | Shared results storage. The share must exist before you install: the chart does not create it. |
| An **Azure Database for PostgreSQL flexible server** the cluster can reach, and its admin login | Holds the FN's databases. The chart creates them for you. |
| A DNS zone you can add a record to (Azure DNS if you want automatic certificates) | The node needs a hostname. |
| `kubectl` and `helm` pointed at the cluster | See [Prerequisites](./Prerequisites). |

Install the Gateway API and Traefik CRDs first ([Prerequisites](./Prerequisites#install-the-gateway-api-and-traefik-crds)).


## 1. Storage: Azure Files

Task pods and Dagster's run pods write results to the same volume, so it must be **ReadWriteMany**. On AKS that means Azure Files. Azure Disk cannot serve it.

Create a Kubernetes secret with the storage account's credentials, in the release namespace. The key names are fixed:

```sh
kubectl create secret generic fn-azure-storage -n federated-node \
  --from-literal=azurestorageaccountname='<your-storage-account-name>' \
  --from-literal=azurestorageaccountkey='<your-storage-account-key>'
```

The chart copies it into the tasks namespace for you. Then point the chart at the secret and the share:

```yaml
storage:
  capacity: 50Gi
  azure:
    secretName: fn-azure-storage
    shareName: files
```

Options under `storage.azure`:

| Key | Default | What it does |
|---|---|---|
| `secretName` | none, required | The secret above. |
| `shareName` | none, required | The file share in that storage account. |
| `resourceGroup` | the AKS node resource group | Set it when the storage account is in a different resource group. |
| `skuName` | `Premium_LRS` | The Azure Files SKU written into the generated StorageClass. |
| `provisioner` | `file.csi.azure.com` | Only change it if you run another driver. |

The chart mounts the share with `file_mode=0777`, `dir_mode=0777`, `nosharesock` and `actimeo=30`, so that a task image running as any user can write. Override them with `fnDagster.artifacts.fileMode`, `fnDagster.artifacts.dirMode`, or replace the whole list with `fnDagster.artifacts.mountOptions`.


## 2. PostgreSQL: Azure Database for PostgreSQL

Azure's flexible server has no role called `postgres`, and it requires TLS. Set both:

```yaml
db:
  host: &dbHost your-server.postgres.database.azure.com
  port: 5432
  superuser: fn_admin          # the admin login you created with the server
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

The server must accept connections from the cluster: allow the cluster's outbound address, or use private access in the same virtual network.


## 3. Ingress and DNS

Use the chart's Traefik (`traefik.enabled: true`). AKS gives its `LoadBalancer` service a public IP. Add a DNS `A` record for your `host` pointing at it:

```sh
kubectl get svc -n federated-node -l app.kubernetes.io/name=traefik
```

To keep the real client address in the logs, set Traefik's external traffic policy:

```yaml
traefik:
  enabled: true
  service:
    spec:
      externalTrafficPolicy: Local
```


## 4. TLS

You have two choices.

**Bring your own certificate.** Create the `tls` secret from [Deploy: Core](./Deploy-Core#3-create-the-namespace-and-the-secrets-you-must-provide) and set `tls.secretName`. Nothing else is needed.

**Automatic renewal with cert-manager and Azure DNS.** The chart can issue and renew a Let's Encrypt certificate with a DNS-01 challenge against an Azure DNS zone. It needs a service principal with the *DNS Zone Contributor* role on the zone, and two objects in the release namespace that you create **before** you install. The install fails at the start, naming whichever is missing.

```sh
kubectl create secret generic fn-azure-ssl-sp -n federated-node \
  --from-literal=SP_SECRET='<service-principal-secret>'
```

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fn-azure-ssl-config
  namespace: federated-node
data:
  EMAIL_CERT: admin@your-institution.example.com
  HOSTED_ZONE: your-institution.example.com
  RG_NAME: your-resource-group
  SP_ID: your-service-principal-app-id
  SUBSCRIPTION_ID: your-subscription-id
  TENANT_ID: your-tenant-id
```

The ConfigMap keys are exactly those six names. The chart copies the secret into the cert-manager namespace.


## 5. Add the Azure block to values.yaml

On top of the file from [Deploy: Core](./Deploy-Core#4-write-your-values-file), replacing its `storage` block:

```yaml
on_aks: true

storage:
  capacity: 50Gi
  azure:
    secretName: fn-azure-storage
    shareName: files
```

With automatic certificates, add:

```yaml
cert-manager:
  enabled: true

certs:
  azure:
    configmap: fn-azure-ssl-config
    secretName: fn-azure-ssl-sp
```

`on_aks: true` only selects the Azure DNS issuer for cert-manager. Storage is chosen by `storage.azure`, not by this flag. Keep `tls.secretName` as it is: the certificate is written to that secret.


## Known issues

- **The file share is not created for you.** A missing share or a wrong key shows up as task pods and the Dagster run pod stuck in `ContainerCreating` with a mount error.
- **Azure Files needs both secret keys.** The names are `azurestorageaccountname` and `azurestorageaccountkey`. The chart fails to render if `storage.azure` has no `secretName` or `shareName`.
- **A dataset on an Azure SQL public endpoint is blocked by default.** The task network policy only allows private address ranges. List the database in `taskNetworkPolicy.datasetEgress`, with both `to` and `ports` ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)). Azure SQL in *redirect* connection mode, and private endpoints whose addresses change, cannot be listed reliably. For those set `taskNetworkPolicy.enabled: false` and manage the tasks namespace's policies yourself.
- **Postgres refuses connections because SSL is off.** Set `db.enforceSSL: true` *and* `dagster.postgresql.postgresqlParams.sslmode: require`: the first covers the backend, the second Dagster. The chart refuses to render if you set only the first.
- **Tasks cannot write to the share.** The default mount options make it writable by any user. If you replaced them with `fnDagster.artifacts.mountOptions`, keep `file_mode` and `dir_mode`.


## Next step

[Post-deploy testing](./Post-Deploy-Testing)
