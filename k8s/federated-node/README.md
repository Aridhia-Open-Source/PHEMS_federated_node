# Federated Node Helm Chart

## values file
The necessary values are:
|path|subpath|description|
|-|-|-|
|storage|capacity|How much to reserve for tasks, defaults to `10Gi`. Other possible units are `Mi`, `Ti`, `Ki`|
|storage|local|If running a cluster off the cloud, this will be the suggested config|
|storage.local|path|Where to persist files in the host machine|
|storage|azure|If running a cluster on azure, or using an Azure Storage Class, this will be the suggested config|
|storage.azure|secretName|Secret name where the credentials for the azure storage are saved|
|storage.azure|shareName|Share name within the azure storage|
|storage.azure|provisioner|Provisioner for azure storage, defaults to disk.csi.azure.com|
|storage.aws|fileSystemId|EFS system id, e.g. fs-xxxxxxxxx|
|storage.aws|accessPointId|Optional, access point id for better permission and isolation management in the EFS|
|-|-|-|
|firstUserSecret|name|The secret name that will hold the password to use for the user|
|firstUserSecret|passKey|The key holding the password|
|firstUserSecret|email|User's email address, this will also be the username|
|firstUserSecret|firstName|(Optional) User's first name|
|firstUserSecret|lastName|(Optional) User's last name|
|-|-|-|
|db|host|DB hostname. One PostgreSQL server is shared by every component|
|db|superuser|Admin login the `*-db-init` hooks connect as. Azure Flexible Server has no `postgres` role|
|db|manageRolesAndDatabases|Create and maintain each component's database, role and grants (default `true`). False means they already exist: no superuser is needed, no passwords are generated, and one secret per role is required instead|
|db.secret|name/key|Where the superuser password lives. Generated when `create_db_deployment` is true; yours when Postgres is external; unused when `manageRolesAndDatabases` is false|
|db|passwords|Optional explicit role passwords, for renders that cannot reach the cluster (ArgoCD, `helm diff`)|
|nexus.api|image/tag/replicas/port|The nexus-api image, replicas and port. It serves `/` and its init container runs the database migrations|
|nexus.api|url|In-cluster URL Dagster, fncli and the smoke tests use to reach nexus-api (default `http://nexus-api.<namespace>.svc:<port>`)|
|nexus.api.db|name/user/secret|nexus-api database, role and password secret (default `fn_nexus`, `fn_nexus`, `nexus-db`)|
|keycloak.db|name/user/secret|Keycloak database, role and password secret|
|keycloak|allowExternalEgress|`false` by default: Keycloak may reach DNS, cluster pods and `privateEgress` only. Set `true` for an external identity provider, or a database on a public address, to leave its egress alone. No effect when `taskNetworkPolicy.enabled` is `false`|
|-|-|-|
|token|life|Duration in seconds for tokens|
|-|-|-|
|taskNetworkPolicy|enabled|Create the NetworkPolicy in the tasks namespace: no ingress, and egress only to DNS, `privateEgress` and `datasetEgress`, so task pods cannot reach the public internet. Also shuts Postgres, Gitea, Dagster and (behind the chart's Traefik) nexus-api, nexus-ui and Keycloak to the tasks namespace, and keeps Postgres, nexus-ui, Traefik and Keycloak off the public internet. Add a public Kubernetes API server address to `privateEgress` (Traefik reads its routes from it). `true` by default; set `false` to manage policies yourself. Needs a CNI that enforces NetworkPolicy|
|taskNetworkPolicy|privateEgress|Private address ranges (CIDRs) task pods may reach on any port. Defaults to `10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16`, which cover in-cluster and private-network databases. Narrow it, or set `[]` to allow DNS and `datasetEgress` only|
|taskNetworkPolicy|datasetEgress|Dataset databases on public addresses (e.g. an Azure SQL public endpoint), as NetworkPolicy egress rules (`to` and `ports`), by address or by namespace and pod label. Empty by default; not needed for a database in the private ranges|
|taskNetworkPolicy|dns|Where task pods may send DNS lookups (UDP and TCP 53), as NetworkPolicy peers. Defaults to kube-dns in `kube-system`|
|-|-|-|
|integrations|domains|The list of third party host that can reach the Federated Node. Otherwise these will be blocked by CSP policies. This will not affect direct user API usage.|
|host|The URL where the FN will be hosted at|
|nodeId|Required. Names this node (hospital) in the results it delivers (`run.json`, `node.id`)|
|tls|secretName|Secret name where the SSL certificate is. Defaults to `tls` if the `tls` section is set|
|customCA|secretName|Optional. An existing Secret holding a CA the node trusts for OUTBOUND TLS, in addition to the system CAs. See [Custom CA](#custom-ca)|
|customCA|key|The key in that Secret holding the PEM, default `ca.crt`|
|customCA|pem|Optional. The PEM itself; the chart renders a Secret `fn-custom-ca` from it. Not together with `secretName`|
|proxy|httpProxy|Optional. Address of an explicit proxy for OUTBOUND `http://` calls, e.g. `http://proxy.example.org:3128`. See [Proxy](#proxy)|
|proxy|httpsProxy|Optional. Address of the proxy for OUTBOUND `https://` calls. The proxy is off unless this or `httpProxy` is set|
|proxy|noProxy|Optional. More hosts and domains that skip the proxy, comma separated. In-cluster addresses always skip it|

### Existing secrets
Most secrets are created by the chart: the per-service database passwords are generated on first
install, reused on every upgrade, and placed in whichever namespace needs them. Read them back with

```sh
kubectl get secret -l federatednode.com/generated-password=true
```

What you have to create yourself, in the release namespace:
- `postgres-superuser` — only when PostgreSQL is external **and** `db.manageRolesAndDatabases` is true
- the `firstUserSecret` secret, if you want to choose the initial admin password
- azure storage credentials, and the tls cert, where those apply

With `db.manageRolesAndDatabases: false` the chart creates no databases or roles and needs no admin
login at all; instead each role's password becomes a secret you supply (`nexus.api.db.secret`,
`keycloak.db.secret` and `global.postgresqlSecretName`). Install once and the chart will print the
exact DDL and `kubectl` commands for your own database and role names, and a `db-check` hook verifies
the credentials before anything else is installed.

### Secrets namespace
Project secrets (dataset credentials, git tokens) are stored in their own namespace,
`global.namespaces.secrets` (default `fn-secrets`), which the chart creates. The release namespace holds
none of them. Dagster's service accounts can read only that namespace, and the backend only that one,
the quarantine and the tasks namespaces. A task gets its dataset credentials from a Secret of its own
(`task-<task_id>-<run_id>`) in the tasks namespace, which the backend creates when the run starts and
deletes when the task ends.

**Upgrading** a node that has secrets from before this change: their rows still name the release
namespace, which Dagster and the backend can no longer read, so tasks and repository checks that use
them fail with `forbidden`. Write each one again with all its values, which stores it in the secrets
namespace and updates its row:

```sh
curl -X PATCH "$FN_URL/global/secrets/<label>" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"values": {"USERNAME": "...", "PASSWORD": "..."}}'
```

Enable any disabled secret **before** upgrading: until its row is written again, a secret from before
this change cannot be enabled, rotated or deleted, and its health check errors. Re-write them after.

On a dev cluster, run `fncli experiment setup` (or tear down and deploy) instead. Then delete the old
copy: `kubectl delete secret fn-secret-<label> -n <release namespace>`.

## Custom CA

Set `customCA` when the node calls out to something signed by a private or self-signed CA, or sits behind a TLS-intercepting proxy: a git host, an identity provider, a container registry. The CA is added to each workload's system CAs and certificates are still verified. There is no option to skip verification. This is separate from `tls.secretName`, the certificate the node serves.

```yaml
customCA:
  secretName: corp-ca   # an existing Secret in the release namespace; key `ca.crt` unless customCA.key says otherwise
  # or, instead, the PEM itself (one CA or a bundle), from which the chart renders a Secret `fn-custom-ca`:
  # pem: |
  #   -----BEGIN CERTIFICATE-----
  #   ...
```

```bash
kubectl create secret generic corp-ca -n <namespace> --from-file=ca.crt=corp-ca.pem
helm upgrade --install ... --set customCA.secretName=corp-ca
```

Setting both `secretName` and `pem` is an error. A Secret you name is copied into the Keycloak namespace by the chart; an inline `pem` is rendered into both.

What gets it:

| Workload | How |
|---|---|
| nexus-api | An init container builds `system CAs + custom CA` into an `emptyDir`; `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE` and `GIT_SSL_CAINFO` point at it |
| Dagster code server | The same |
| Dagster run pods (clone, push, deliver results) | The code server hands the same volumes, init container and env to the Dagster launcher as a container context, so each run pod gets them |
| Keycloak | `KC_TRUSTSTORE_PATHS` points at the PEM mounted from the Secret; Keycloak keeps trusting its system CAs |

Not covered, on purpose or because the chart cannot: task (pipes) pods run partner code with no outbound access and are not given it; the Dagster webserver and daemon belong to the Dagster subchart, whose values the chart cannot template, and make no outbound HTTPS calls; the kubelet and containerd pull images with the node's own trust store, so a registry behind a private CA needs that CA on every node, which the cluster operator sets up.

Rotation: the bundle is built when a pod starts, so the pods restart when the CA changes. With `pem`, or a Secret that Helm can read, `helm upgrade` does it through a `checksum/custom-ca` pod annotation. A Secret managed outside Helm and changed in place is not noticed: run `kubectl rollout restart deployment/nexus-api deployment/<release>-dagster-fn -n <namespace>` and `kubectl rollout restart statefulset/keycloak -n <keycloak namespace>`, or use a reloader controller. New Dagster run pods read the current Secret when they start. Where the chart cannot read the cluster (`helm template`, `helm diff`) the annotation hashes the Secret's name and key only.

## Proxy

`customCA` makes the node trust a proxy's certificate. It does not tell the node the proxy exists. Behind an explicit proxy, also set `proxy`, or the pods trust it but never use it and calls such as the Dagster sensors' to GitHub fail. The two go together when the proxy intercepts TLS.

```yaml
proxy:
  httpsProxy: http://proxy.example.org:3128
  httpProxy: http://proxy.example.org:3128   # optional, only for plain http:// calls
  noProxy: .corp.example,10.20.0.0/16        # optional, more hosts that skip the proxy
customCA:
  secretName: corp-ca
```

The chart sets `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY` in upper and lower case, because tools differ in which they read, on nexus-api, the Dagster code server, the Dagster run pods and Keycloak. Nothing is set unless `httpsProxy` or `httpProxy` is. `NO_PROXY` always starts with `localhost,127.0.0.1,.svc,.svc.cluster.local,.cluster.local` and the Kubernetes API server address, so calls between the node's own services skip the proxy; your `noProxy` follows. Task (pipes) pods have no outbound access and are not given it.

The proxy address is stored as plain text in the pod specs, so do not put credentials in it.

## Gateway API CRD update
```sh
VERSION=x.y.z
wget "https://github.com/kubernetes-sigs/gateway-api/releases/download/v${VERSION}/standard-install.yaml -O k8s/federated-node/scripts/gateway-api-crds-${VERSION//./-}.yaml"
```
