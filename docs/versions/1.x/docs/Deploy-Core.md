# Deploy: Core

This guide covers the steps common to **all platforms**. Work through this alongside the platform-specific guide for your environment ([Azure](Deploy-Azure.md), [AWS](Deploy-AWS.md), [GCP](Deploy-GCP.md) or [On-Premises](Deploy-On-Premises.md)). The platform-specific guides contain additional values to be added to your `values.yaml` file and additional secrets that must exist before running `helm install`


## 1. Add the Helm repository

```sh
helm repo add federated-node https://aridhia-open-source.github.io/PHEMS_federated_node
helm repo update
```

Check available versions:

```sh
# Stable releases
helm search repo federated-node --versions

# Include development/pre-release builds
helm search repo federated-node --devel --versions
```


## 2. Create a namespace (recommended)

```sh
kubectl create namespace federated-node
```

Append `-n federated-node` to all `kubectl` commands in this guide, or omit it if deploying to the default namespace.


## 3. Create the database credentials secret

The FN needs credentials to connect to your PostgreSQL instance. Store the password in a Kubernetes secret:

```sh
kubectl create secret generic fn-db-secret \
    --from-literal=value="<your-db-password>" \
    -n federated-node
```

Or via YAML (value must be base64-encoded - `echo -n "yourpassword" | base64`):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fn-db-secret
  namespace: federated-node
data:
  value: <base64-encoded-password>
type: Opaque
```


## 4. Create the first user secret

From v1.5.0 the chart can create an initial admin user automatically. The password must be stored in a Kubernetes secret - `name`, `passKey`, and `email` are all required if you use `firstUserSecret`.

```sh
kubectl create secret generic fn-first-user \
    --from-literal=password="<your-chosen-password>" \
    -n federated-node
```

You'll reference this secret by name in `values.yaml` (step 5). If you skip this, you can retrieve the auto-generated Keycloak admin password from the `kc-secrets` secret after deployment:

```sh
kubectl get secret -n federated-node kc-secrets -o json \
  | jq -r '.data.KEYCLOAK_ADMIN_PASSWORD' | base64 -d
```


## 5. Create the TLS secret (if not using cert-manager)

If you already have a certificate:

```sh
kubectl create secret tls tls \
    --key key.pem \
    --cert cert.crt \
    -n federated-node
```

For automatic certificate renewal, see the cert-manager section in your platform-specific guide.

For local development, you can create a self signed certificate using the following example
```
HOST=fn.example.com

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
     -keyout key.pem -out cert.pem \ 
     -subj "/CN=${HOST}/O=${HOST}" -addext "subjectAltName = DNS:${HOST}"

kubectl create secret tls tls \
    --key key.pem \
    --cert cert.crt \
    -n federated-node
```


## 6. Pre-install Gateway API and Traefik CRDs (if using Traefik)

If `traefik.enabled: true`, these CRDs must exist before `helm install` or the chart will fail. See [Prerequisites](Prerequisites.md#critical-pre-install-gateway-api-and-traefik-crds) for the install command.


## 7. Create your values.yaml

Create `values.yaml`. At minimum you need:

```yaml
# Public hostname where the FN will be accessible
host: fn.your-institution.example.com

# PostgreSQL connection for FN internal metadata (not your research data)
db:
  host: your-postgres-host.example.com
  name: federated_node_db
  port: 5432
  user: fn_user
  secret:
    name: fn-db-secret   # secret name from step 3
    key: value            # key within that secret

# First admin user (v1.5.0+)
firstUserSecret:
  name: fn-first-user    # secret name from step 4
  passKey: password      # key within that secret holding the password
  email: admin@your-institution.example.com
  firstName: Admin
  lastName: User

# Traefik ingress (recommended for production)
traefik:
  enabled: true
```

Then add the platform-specific storage block from your platform guide. See the [Helm Values Reference](Helm-Values-Reference.md) for all options.


## 8. Deploy

```sh
helm install federatednode federated-node/federated-node \
    -f values.yaml \
    --namespace federated-node
```

To deploy into the default namespace, omit `--namespace`.

To upgrade an existing deployment:

```sh
helm upgrade federatednode federated-node/federated-node \
    -f values.yaml \
    --namespace federated-node
```

Note: the release name is `federatednode` (no hyphen). Use this exact name for all subsequent `helm` commands against this release.


## 9. Check pod status

```sh
kubectl get pods -n federated-node
kubectl get pods -n keycloak
```

All pods should reach `Running` status. Keycloak and the backend API pods can take 2-3 minutes on first boot. If anything is stuck, check logs:

```sh
kubectl logs -n federated-node deployment/backend
kubectl logs -n keycloak statefulset/keycloak
```

**Common causes of failure:**

- `Pending` - storage PV not provisioned, or insufficient cluster resources
- `CrashLoopBackOff` on backend - database unreachable, or `db.secret` references a non-existent secret
- `CrashLoopBackOff` on Keycloak - database unreachable
- Helm install error about missing CRDs - Gateway API or Traefik CRDs not pre-installed (see step 6)


## Next step

Once your pods are running, go to [Post-Deploy Testing](Post-Deploy-Testing.md) to verify everything works end-to-end.
