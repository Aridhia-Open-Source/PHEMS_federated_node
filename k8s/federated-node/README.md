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
|backend.db|name/user/secret|Backend database, role and password secret|
|keycloak.db|name/user/secret|Keycloak database, role and password secret|
|-|-|-|
|token|life|Duration in seconds for tokens|
|-|-|-|
|integrations|domains|The list of third party host that can reach the Federated Node. Otherwise these will be blocked by CSP policies. This will not affect direct user API usage.|
|host|The URL where the FN will be hosted at|
|tls|secretName|Secret name where the SSL certificate is. Defaults to `tls` if the `tls` section is set|
|customCA|secretName|Optional. An existing Secret holding a CA the node trusts for OUTBOUND TLS, in addition to the system CAs. See [Custom CA](#custom-ca)|
|customCA|key|The key in that Secret holding the PEM, default `ca.crt`|
|customCA|pem|Optional. The PEM itself; the chart renders a Secret `fn-custom-ca` from it. Not together with `secretName`|

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
login at all; instead each role's password becomes a secret you supply (`backend.db.secret`,
`keycloak.db.secret` and `global.postgresqlSecretName`). Install once and the chart will print the
exact DDL and `kubectl` commands for your own database and role names, and a `db-check` hook verifies
the credentials before anything else is installed.

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
| Backend | An init container builds `system CAs + custom CA` into an `emptyDir`; `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE` and `GIT_SSL_CAINFO` point at it |
| Dagster code server | The same |
| Dagster run pods (clone, push, deliver results) | The code server hands the same volumes, init container and env to the Dagster launcher as a container context, so each run pod gets them |
| Keycloak | `KC_TRUSTSTORE_PATHS` points at the PEM mounted from the Secret; Keycloak keeps trusting its system CAs |

Not covered, on purpose or because the chart cannot: task (pipes) pods run partner code with no outbound access and are not given it; the Dagster webserver and daemon belong to the Dagster subchart, whose values the chart cannot template, and make no outbound HTTPS calls; the kubelet and containerd pull images with the node's own trust store, so a registry behind a private CA needs that CA on every node, which the cluster operator sets up.

Rotation: the bundle is built when a pod starts, so the pods restart when the CA changes. With `pem`, or a Secret that Helm can read, `helm upgrade` does it through a `checksum/custom-ca` pod annotation. A Secret managed outside Helm and changed in place is not noticed: run `kubectl rollout restart deployment/backend deployment/<release>-dagster-fn -n <namespace>` and `kubectl rollout restart statefulset/keycloak -n <keycloak namespace>`, or use a reloader controller. New Dagster run pods read the current Secret when they start. Where the chart cannot read the cluster (`helm template`, `helm diff`) the annotation hashes the Secret's name and key only.

## Gateway API CRD update
```sh
VERSION=x.y.z
wget "https://github.com/kubernetes-sigs/gateway-api/releases/download/v${VERSION}/standard-install.yaml -O k8s/federated-node/scripts/gateway-api-crds-${VERSION//./-}.yaml"
```
