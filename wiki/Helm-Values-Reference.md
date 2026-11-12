# Helm Values Reference

Complete reference for all configuration fields in the Federated Node Helm chart `values.yaml`.

All fields are optional unless marked **required**.

---

## General

| Field | Description | Default |
|---|---|---|
| `host` | Public URL where the FN will be hosted. Also used to name result files. | - |
| `cleanupTime` | Days to retain task results and related Kubernetes resources. Cleanup runs daily at noon via a CronJob. | `3` |
| `taskReview` | Enable the results review/approval workflow (see [Task Review](Task-Review.md)) | `false` |
| `outboundMode` | Deploy the Federated Node Task Controller as a subchart | `false` |
| `smoketests` | Enable smoke test endpoints for `helm test` | `false` |
| `on_aks` | Set to `true` when deploying on Azure AKS | `false` |
| `on_eks` | Set to `true` when deploying on AWS EKS | `false` |
| `pullPolicy` | Image pull policy for all FN images. Options: `Always`, `IfNotPresent` | `Always` |

---

## Backend

| Field | Description | Default |
|---|---|---|
| `backend.replicas` | Number of backend pod replicas | `1` |
| `backend.tag` | Override the backend image tag (for testing specific versions) | Chart `appVersion` |
| `federatedNode.port` | Backend service port | `5000` |
| `federatedNode.volumes.results_path` | Mount path for results storage inside the backend pod | `/mnt/results` |
| `federatedNode.volumes.task_pod_results_path` | Mount path for results storage inside analytics task pods | `/mnt/data` |
| `federatedNode.enable_image_whitelist` | Restrict task execution to images on the allowlist. When `false`, any image from a registered registry is permitted. | `false` |
| `federatedNode.allow_delivery_api` | Automatically deliver results when a task completes via direct API call (not just Task Controller triggers) | `false` |

---

## Keycloak

| Field | Description | Default |
|---|---|---|
| `keycloak.replicas` | Number of Keycloak pod replicas | `2` |
| `keycloak.tag` | Override the Keycloak image tag | Chart `appVersion` |

---

## Database (required)

The fields `db.host`, `db.user`, and `db.secret` are required.

| Field | Description | Default |
|---|---|---|
| `db.host` | **Required.** PostgreSQL hostname | - |
| `db.user` | **Required.** Database username | - |
| `db.secret.name` | **Required.** Kubernetes secret containing the password | - |
| `db.secret.key` | **Required.** Key within the secret where the password is stored | - |
| `db.name` | Database name | `fndb` |
| `db.port` | Database port | `5432` |
| `db.enforceSSL` | Enforce SSL on the FN backend's connection to PostgreSQL | `false` |

---

## First user (v1.5.0+)

If `firstUserSecret` is provided, `name`, `passKey`, and `email` are all required. The secret holding the password must exist in the same namespace before deploying.

| Field | Description | Default |
|---|---|---|
| `firstUserSecret.name` | **Required if using firstUserSecret.** Kubernetes secret name containing the password | - |
| `firstUserSecret.passKey` | **Required if using firstUserSecret.** Key within the secret holding the password | - |
| `firstUserSecret.email` | **Required if using firstUserSecret.** User's email address (also used as the login username) | - |
| `firstUserSecret.firstName` | User's first name (optional) | - |
| `firstUserSecret.lastName` | User's last name (optional) | - |

If `firstUserSecret` is omitted, retrieve the auto-generated Keycloak admin password post-deploy:
```sh
kubectl get secret -n <namespace> kc-secrets -o json | jq -r '.data.KEYCLOAK_ADMIN_PASSWORD' | base64 -d
```

---

## Storage

Exactly one of `azure`, `aws`, `nfs`, or `local` must be provided.

| Field | Description | Default |
|---|---|---|
| `storage.capacity` | Persistent volume size for task results | `10Gi` |
| `storage.mountOptions` | List of mount options passed to the storage volume | `[]` |
| `storage.azure.secretName` | Kubernetes secret with Azure Storage Account credentials | - |
| `storage.azure.shareName` | Azure file share name | - |
| `storage.azure.provisioner` | Override the Azure storage class provisioner | `disk.csi.azure.com` |
| `storage.aws.fileSystemId` | **Required for AWS.** EFS filesystem ID (e.g. `fs-xxxxxxxxx`) | - |
| `storage.aws.accessPointId` | **Required for AWS.** EFS access point ID | - |
| `storage.nfs.provisioner` | NFS storage class provisioner name | - |
| `storage.nfs.url` | NFS server hostname or IP | - |
| `storage.nfs.path` | Path on the NFS server | - |
| `storage.local.path` | Host path for results storage (local/on-prem only) | - |
| `storage.local.dbpath` | Host path for DB storage - only used when `create_db_deployment: true` | - |

---

## Dataset volumes

Read-only volumes holding DuckDB/SQLite files for [file datasets](Datasets.md#file-datasets-duckdb-and-sqlite). Each entry creates a `ReadOnlyMany` PV, and a PVC named `name` in the tasks namespace to use as the dataset's `volume_claim`. Set exactly one of `local`, `azure`, `aws`, `gcp` or `nfs` per entry.

| Field | Description | Default |
|---|---|---|
| `datasetVolumes[].name` | PVC name, referenced by the dataset's `volume_claim` | - |
| `datasetVolumes[].capacity` | Volume size | `10Gi` |
| `datasetVolumes[].mountOptions` | List of mount options | `[]` |
| `datasetVolumes[].local.path` | Directory on the node | - |
| `datasetVolumes[].azure.shareName` | Azure file share name | - |
| `datasetVolumes[].azure.secretName` | Secret with the storage account credentials | `azure-storage-secret` |
| `datasetVolumes[].azure.secretNamespace` | Namespace of that secret | - |
| `datasetVolumes[].aws.fileSystemId` | EFS filesystem ID | - |
| `datasetVolumes[].aws.accessPointId` | EFS access point ID (optional) | - |
| `datasetVolumes[].gcp.bucketName` | GCS bucket, mounted via GCS FUSE | - |
| `datasetVolumes[].nfs.url` | NFS server hostname or IP | - |
| `datasetVolumes[].nfs.path` | Path on the NFS server | - |

---

## Namespaces

| Field | Description | Default |
|---|---|---|
| `namespaces.keycloak` | Namespace for Keycloak pods | `keycloak` |
| `namespaces.tasks` | Namespace where analytics task pods run | `tasks` |
| `namespaces.controller` | Namespace for the Task Controller pods | `fn-controller` |

---

## Token

| Field | Description | Default |
|---|---|---|
| `token.life` | Auth token lifetime in seconds | `2592000` (30 days) |

---

## Networking and access control

| Field | Description | Default |
|---|---|---|
| `integrations.domains` | List of third-party origins permitted by CORS/CSP policy. Only relevant when a web UI accesses the FN - does not affect direct API usage. | `[self]` |
| `whitelist.enabled` | Enable IP CIDR allowlist | - |
| `whitelist.ips` | List of allowed IP CIDRs | - |
| `blacklist.enabled` | Enable IP CIDR blocklist | - |
| `blacklist.ips` | List of blocked IP CIDRs | - |

---

## TLS

| Field | Description | Default |
|---|---|---|
| `tls.secretName` | Kubernetes secret name containing the TLS certificate | `tls` |

---

## Traefik (ingress)

| Field | Description | Default |
|---|---|---|
| `traefik.enabled` | Enable the Traefik reverse proxy subchart. **Requires Gateway API and Traefik CRDs to be pre-installed.** See [Prerequisites](Prerequisites.md). | `false` |
| `traefik.gateway.enabled` | Enable the Traefik Gateway resource | `false` |
| `traefik.gateway.name` | Name of the Gateway resource | `traefik-fn-gateway` |
| `traefik.gatewayClass.name` | Name of the GatewayClass | `traefik-fn-gateway-class` |
| `traefik.api.dashboard` | Enable the Traefik dashboard | `false` |
| `traefik.service.spec.externalIPs` | List of external IPs to assign to the Traefik service | - |
| `traefik.service.spec.externalTrafficPolicy` | AKS deployments only. Options: `Local`, `Cluster` | `Local` |

---

## Automatic certificate renewal (cert-manager)

| Field | Description | Default |
|---|---|---|
| `cert-manager.enabled` | Enable the cert-manager subchart | `false` |
| `cert-manager.namespace` | Namespace for cert-manager resources | `fn-certmanager` |
| `cert-manager.installCRDs` | Install cert-manager CRDs automatically | `true` |
| `certs.rotationPolicy` | Certificate rotation policy | `Never` |
| `certs.azure.secretName` | Secret name for the Azure SP used in SSL renewal | - |
| `certs.azure.configmap` | ConfigMap name for Azure SP SSL renewal configuration | - |
| `certs.aws` | Secret name containing AWS Route 53 credentials for SSL renewal | - |

---

## Task Controller subchart

These fields are only used when `outboundMode: true`. See [Task Controller: Deploy](https://github.com/Aridhia-Open-Source/federated-node-task-controller/wiki/Deploy) for full details.

| Field | Description | Default |
|---|---|---|
| `fn-task-controller.controller.tag` | Task Controller image tag | Chart `appVersion` |
| `fn-task-controller.controller.skipUserAuth` | Skip GitHub identity verification. When `true`, tasks run as the controller's system user rather than verifying the submitting GitHub user. | `true` |
| `fn-task-controller.controller.vol_path` | Internal volume mount path for the controller | - |
| `fn-task-controller.storage.*` | Same structure as main `storage.*`, including `mountOptions` | - |
| `fn-task-controller.idp.github.secret_name` | Kubernetes secret name containing the GitHub App credentials | - |
| `fn-task-controller.idp.github.secret_key` | Key in the secret for the GitHub App client secret | - |
| `fn-task-controller.idp.github.clientid_key` | Key in the secret for the GitHub App client ID | - |
| `fn-task-controller.idp.github.orgAndRepo` | GitHub `org/repo` that researchers submit tasks from | - |
| `fn-task-controller.delivery.github.repository` | GitHub `org/repo` where results are pushed | - |
| `fn-task-controller.delivery.other.url` | Alternative delivery destination hostname (no `http://` prefix) | - |
| `fn-task-controller.delivery.other.auth_type` | Auth type for other delivery. Options: `Bearer`, `AzCopy`, `Basic` | - |

---

## Development-only fields

These fields exist for local development and should not be used in production.

| Field | Description | Default |
|---|---|---|
| `local_development` | Disables SSL validation - for local development only | `false` |
| `create_db_deployment` | Deploy an in-cluster PostgreSQL instance - unstable, not for production | `false` |
