# Deploy: Core

This guide installs the Federated Node 2.x on a cluster you already have. It covers the steps common to **all platforms**. Work through [Prerequisites](./Prerequisites) first, then use the guide for your platform alongside this one.


## Platform guides

Each platform has its own prerequisites, storage, database, ingress and DNS, and certificate settings, and its own known issues. This page does not repeat them.

| Platform | Guide | Results storage | Automatic certificates |
|---|---|---|---|
| Azure (AKS) | [Deploy: Azure](./Deploy-Azure) | Azure Files (`storage.azure`) | Azure DNS (`certs.azure`) |
| AWS (EKS) | [Deploy: AWS](./Deploy-AWS) | EFS (`storage.aws`) | Route 53 (`certs.aws`) |
| Google (GKE) | [Deploy: GCP](./Deploy-GCP) | Filestore over NFS (`storage.nfs`) | Your own cert-manager with Cloud DNS |
| On-premises (RKE2, k3s, kubeadm) | [Deploy: On-Premises](./Deploy-On-Premises) | NFS (`storage.nfs`), or a local path on one node | Your own certificate or cert-manager |

Everything below applies on every platform.


## 1. Add the Helm repository

```sh
helm repo add federated-node https://aridhia-open-source.github.io/PHEMS_federated_node
helm repo update
helm search repo federated-node --devel --versions
```

The 2.x line is published as pre-releases, so it only shows with `--devel`. Pick the newest `2.0.0-...` entry and pin it with `--version` in step 5.

Leave `default_image_tag` unset. Every image tag then follows the chart's `appVersion`, so the chart and the images always move together.


## 2. Install the CRDs

If you use the chart's Traefik, install the Gateway API and Traefik CRDs once per cluster. See [Prerequisites](./Prerequisites#install-the-gateway-api-and-traefik-crds).


## 3. Create the namespace and the secrets you must provide

```sh
kubectl create namespace federated-node
```

The chart creates every database password, the Keycloak credentials and the Dagster login for you, and puts them in the namespaces that need them. These are the ones it cannot invent:

| Secret | Key | When | What it is |
|---|---|---|---|
| `postgres-superuser` | `password` | Postgres is external and `db.manageRolesAndDatabases` is true (the default) | Password of `db.superuser` on your server |
| the secret named by `firstUserSecret.name` | the key in `firstUserSecret.passKey` | Always | Password of the first admin user. The chart copies it to the Keycloak namespace |
| `tls` (or the name in `tls.secretName`) | `tls.crt`, `tls.key` | No cert-manager | The certificate for `host`, full chain |
| the Azure storage secret | `azurestorageaccountname`, `azurestorageaccountkey` | `storage.azure` | The chart copies it to the tasks namespace |

```sh
kubectl create secret generic postgres-superuser -n federated-node \
  --from-literal=password='<postgres admin password>'

kubectl create secret generic fn-first-user -n federated-node \
  --from-literal=password='<admin password you will log in with>'

kubectl create secret tls tls -n federated-node \
  --cert server.crt --key server.key
```

Git and dataset credentials are **not** Helm secrets. You register them through the API after the install, as global secrets.


## 4. Write your values file

Start from this example, then replace its `storage` block with the one in your platform guide. It renders cleanly with `helm template`.

```yaml
# The public hostname. Needs a DNS record pointing at Traefik, and a certificate.
host: fn.your-institution.example.com

# Names this node in the results it delivers (run.json, node.id). Required.
nodeId: your-institution

# One external Postgres server shared by every component.
db:
  host: &dbHost postgres.your-institution.example.com
  port: 5432
  # The admin login the *-db-init jobs use to create each database and role.
  # Managed Postgres has no role called "postgres" (Azure, RDS, Cloud SQL): set yours.
  superuser: fn_admin
  enforceSSL: true
  secret:
    name: postgres-superuser     # the secret from step 3
    key: password

# The first admin user. Its password is the secret from step 3.
firstUserSecret:
  name: fn-first-user
  passKey: password
  email: admin@your-institution.example.com
  firstName: Admin
  lastName: User

# Shared storage for results. Use ONE of azure, aws, nfs, local (see Shared storage below).
storage:
  capacity: 50Gi
  nfs:
    provisioner: nfs.csi.k8s.io
    url: 192.168.1.100
    path: /exports/federated-node

# Ingress. The chart's own Traefik, with the Gateway API.
traefik:
  enabled: true

tls:
  secretName: tls

# Origins allowed to call the API from a browser (CSP).
integrations:
  domains:
    - https://fn.your-institution.example.com

# Dagster is off by default and has to be switched on.
dagster:
  enabled: true
  postgresql:
    # Must equal db.host. Helm cannot template a subchart value, so it is written
    # twice (the anchor keeps them together). The chart fails to render if they differ.
    postgresqlHost: *dbHost
    # Needed when db.enforceSSL is true, and the chart insists on it:
    postgresqlParams:
      sslmode: require
```

Things that are easy to get wrong:

- **`nodeId` is required.** The chart fails without it.
- **`dagster.enabled` is false by default.** Without it nothing polls git and no task runs.
- **Do not set `fnDagster.db`:** the chart fails if you do. Dagster's database name and user come from `dagster.postgresql.postgresqlDatabase` and `postgresqlUsername`.
- **`namespaces` lives under `global`** (`global.namespaces.keycloak`, `.tasks`, `.quarantine`). A top-level `namespaces` fails the render.
- **Datasets are not configured here.** Register them through the API.
- **Task CPU and memory** come from `taskCompute.default` and `taskCompute.max`. A task spec that asks for more than the max is rejected.
- Optional: `smoketests: true` lets `helm test` create and delete real rows.

Every value, with comments, is in the chart's [values.yaml](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/k8s/federated-node/values.yaml), and `values.schema.json` beside it says which are required.

### Shared storage

Set exactly one backend under `storage`. The same volume class is used for task results and for Dagster's artifacts.

| Backend | Values | Also needs | Guide |
|---|---|---|---|
| Azure Files | `storage.azure.secretName`, `.shareName` | The file share exists already, plus the storage secret | [Azure](./Deploy-Azure#1-storage-azure-files) |
| AWS EFS | `storage.aws.fileSystemId`, `.accessPointId` (both required) | The EFS CSI driver, and an access point | [AWS](./Deploy-AWS#1-storage-efs) |
| NFS | `storage.nfs.url`, `.path`, `.provisioner` | The export is writable by uid 1000: `chown 1000:1000` and `chmod 775` | [On-Premises](./Deploy-On-Premises#nfs-recommended-for-multi-node-clusters), [GCP](./Deploy-GCP#1-storage-filestore-over-nfs) |
| Local path | `storage.local.artifacts` (and `.dbpath` for the chart's own development Postgres) | Single node only; the pods are pinned to the node that holds the data | [On-Premises](./Deploy-On-Premises#local-host-path-single-node-only) |

The schema allows exactly one of `azure`, `aws`, `nfs` and `local`.

Set `storage.nfs.provisioner` (for example `nfs.csi.k8s.io`) even without that driver installed: the chart writes it into the artifacts StorageClass, which is invalid empty.

### TLS

Either create the `tls` secret yourself (step 3), or let cert-manager renew it. The chart's own issuer exists for Azure DNS and Route 53 only: `cert-manager.enabled: true` plus `certs.azure.*` ([Azure](./Deploy-Azure#4-tls)) or `certs.aws` ([AWS](./Deploy-AWS#4-tls)). For any other CA or DNS provider (GCP, on-premises), run cert-manager yourself and point `tls.secretName` at the secret it produces, and leave `cert-manager.enabled` off.

### Databases

By default the chart manages the databases: three init jobs connect as `db.superuser` and create `backend`, `keycloak_db` and `dagster`, each with its own role and a generated password. Re-running them is harmless. The names come from `backend.db.name`, `keycloak.db.name` and `dagster.postgresql.postgresqlDatabase`.

If a DBA owns the databases and you have no admin login, set `db.manageRolesAndDatabases: false`. The chart then needs no superuser, creates nothing, and each role's password becomes a secret you supply. Install once and it prints the exact SQL and `kubectl` commands for your names. A `db-check` hook verifies the roles before anything else installs.

For `helm diff`, External Secrets, Sealed Secrets or Vault, set `db.createPasswordSecrets: false` and let that tool own the password secrets. The chart reads them at runtime and never needs the value at render time. Left to generate one, a render without cluster access would emit a new password secret every time.

### Let tasks reach their dataset

The chart puts a NetworkPolicy in the tasks namespace: no traffic in, and out only to cluster DNS, to the private address ranges in `taskNetworkPolicy.privateEgress` (`10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16` by default), and to the rules in `taskNetworkPolicy.datasetEgress`. A dataset database on a private address needs no listing. **A task whose dataset database is on any other address, such as a public endpoint, times out when it connects** unless you list it in `datasetEgress`, by address or by namespace and pod label:

```yaml
taskNetworkPolicy:
  datasetEgress:
    - to:
        - ipBlock:
            cidr: 10.20.30.40/32      # your dataset database
      ports:
        - protocol: TCP
          port: 5432
```

A rule needs both `to` and `ports`, or the chart refuses to render. The policy only works if your cluster's network plugin enforces NetworkPolicy. To manage the tasks namespace's policies yourself, set `taskNetworkPolicy.enabled: false`.


## 5. Install

Check the file renders first. This needs no cluster:

```sh
helm template federatednode federated-node/federated-node \
  --devel --version <VERSION> -f values.yaml --namespace federated-node > /dev/null
```

Then install. The release name is `federatednode` throughout the docs, and some service names derive from it (`federatednode-dagster-webserver`), so keep it.

```sh
helm upgrade --install federatednode federated-node/federated-node \
  --devel --version <VERSION> \
  -f values.yaml \
  --namespace federated-node \
  --timeout 15m
```

The install reads the live cluster, so missing CRDs and missing secrets fail it at the start with a message that says what to create. Fix it and run the same command again.


## 6. Check it

Follow [Post-deploy testing](./Post-Deploy-Testing). All Dagster sensors start **stopped**, so nothing runs until you set up a project and start them ([Operations](./Operations#start-the-sensors)).

> **Never publish the Dagster UI.** It has no login of its own. Anyone who can reach it can start, cancel and read runs. The chart creates no route for it on purpose: reach it with a port-forward, and treat that access as cluster access.


## 7. Cluster hardening

The FN pods run non-root, with no privilege escalation and all capabilities dropped. They fit the `restricted` Pod Security Standard. The `tasks` namespace runs whatever analytics images researchers supply, so use `baseline` there unless you control them all:

```sh
kubectl label namespace federated-node pod-security.kubernetes.io/enforce=restricted
kubectl label namespace keycloak       pod-security.kubernetes.io/enforce=restricted
kubectl label namespace tasks          pod-security.kubernetes.io/enforce=baseline
```

The chart creates a `ClusterRole` for the backend, so the user running `helm install` must be allowed to create cluster roles. The tasks namespace must hold nothing but task pods: the chart refuses to render if `global.namespaces.tasks` is the release or Keycloak namespace.

With the same switch the node's own services refuse traffic from the tasks namespace, and Postgres, Traefik and Keycloak get no route to the public internet: only cluster DNS, cluster pods and `privateEgress`. Two things follow:

- If your cluster's Kubernetes API server is on a public address, add it to `taskNetworkPolicy.privateEgress`, or Traefik cannot read its routes.
- If Keycloak must reach an external identity provider, or a database on a public address, set `keycloak.allowExternalEgress: true`.


## Upgrade, uninstall, reinstall

**Upgrade** with the same command as the install and a new `--version`. Passwords are reused, and the backend applies database migrations itself (an init container runs them before it starts).

```sh
helm repo update
helm upgrade --install federatednode federated-node/federated-node \
  --devel --version <NEW_VERSION> -f values.yaml -n federated-node --timeout 15m
```

**Uninstall** with `helm uninstall federatednode -n federated-node`. Helm does not remove what the hooks created: the generated password secrets (label `federatednode.com/generated-password=true`), the init jobs, the dataset credential secrets the backend wrote, and the data behind the Postgres volume if the chart ran the database.

**Reinstall onto the same external database server** works: the init jobs set each role's password to the newly generated one, and the databases and their data are still there. Drop the databases first if you want a clean start.


## Chart versions

CI builds the images and packages the chart on every push, and the branch decides the version suffix:

| Branch | Chart and image version | Use |
|---|---|---|
| a release tag | `2.0.0` | Production |
| `main` | `2.0.0-rc.N` | Release candidate |
| `develop` | `2.0.0-beta.N` | Integration |
| `dagster-main` | `2.0.0-dagster-beta.N` | The Dagster line before it joins `main` |
| `dagster-develop` | `2.0.0-dagster-alpha.N` | Earliest builds of that line |

Use `--devel` for anything with a suffix. The full install guide is the repo's [DEPLOYMENT.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/DEPLOYMENT.md).
