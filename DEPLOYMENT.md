# Federated Node Deployment Instructions

### Prerequisite
The federated node is deployed as an Helm Chart, so helm should be installed in your system.

See their installation instructions [here](https://helm.sh/docs/intro/install/).

### Setup helm repo
```sh
helm repo add federated-node https://aridhia-open-source.github.io/PHEMS_federated_node

# Check available releases
helm search repo federated-node --versions

# If you want to check development builds
helm search repo federated-node --devel --versions
```

Now you should be all set to pull the chart from GitHub.

### Pre-existing Secrets (optional)
In order to not store credentials in plain text within the `values.yaml` file, there is an option to pre-populate secrets in a safe matter.

Just keep in mind that some characters need to be escaped. i.e. `"` has to be `\"` in the bash commands. Currently, we only detected `"` and `%` to be problematic characters.

The secrets to be created are:
- Db credentials for the FN webserver to use (not where the dataset is)
- Azure storage account credentials (if used)

If you plan to deploy on a dedicated namespace, create it manually first or the secrets creation will fail
```sh
kubectl create namespace <new namespace name>
```

__Please keep in mind that every secret value has to be a base64 encoded string if using the yaml templates. Via command line this conversion is done for you__ It can be achieved with the following command:
```sh
echo -n "value" | base64
```

#### Database
In case you want to set DB secrets the structure is slightly different:

```sh
kubectl create secret generic $secret_name \
    --from-literal=value="$password"
```
or using the yaml template:
```yaml
apiVersion: v1
kind: Secret
metadata:
    # set a name of your choosing
    name:
    # use the namespace name in case you plan to deploy in a non-default one.
    # Otherwise you can set to default, or not use the next field altogether
    namespace:
data:
  value:
type: Opaque
```

#### Azure Storage

_Note: The azure storage account file share has to exist already_
```sh
kubectl create secret generic $secret_name \
    --from-literal=azurestorageaccountkey="$accountkey" \
    --from-literal=azurestorageaccountname="$accountname"
```
or using the yaml template:
```yaml
apiVersion: v1
kind: Secret
metadata:
    # set a name of your choosing
    name:
    # use the namespace name in case you plan to deploy in a non-default one.
    # Otherwise you can set to default, or not use the next field altogether
    namespace:
data:
  azurestorageaccountkey:
  azurestorageaccountname:
type: Opaque
```

#### TLS Certificates
If a certificate needs to be generated, follow the official nginx [documentation article](https://github.com/kubernetes/ingress-nginx/blob/main/docs/user-guide/tls.md#tls-secrets).

Granted that the `pem` and `crt` file already in the current working folder, run:
```sh
kubectl create secret tls tls --key key.pem --cert cert.crt
```
This will create a special kubernetes secret in the default namespace, append `-n namespace_name` to create it in a specific namespace (i.e. the one where the chart is going to be deployed on)

##### Automatic certificate renewal
The `cert-manager` tool will be used to provide this functionality. It is disabled by default, if it's needed, set `certmanager.enabled` to `true` in your values file at deployment time.

If used, it will need few information based on which cloud platform it needs to interface with.

##### Azure
```sh
kubectl create secret generic $secret_name \
    --from-literal=CLIENT_SECRET="$SP_SECRET"
```
or using the yaml template:
```yaml
apiVersion: v1
kind: Secret
metadata:
    # set a name of your choosing
    name:
    # use the namespace name in case you plan to deploy in a non-default one.
    # Otherwise you can set to default, or not use the next field altogether
    namespace:
data:
  CLIENT_SECRET:
type: Opaque
```
In addition, a ConfigMap is needed with the less sensitive data:
```sh
kubectl create configmap $configmap \
    --from-literal=CLIENT_ID="$CLIENT_ID" \
    --from-literal=EMAIL_CERT="$EMAIL_CERT" \
    --from-literal=HOSTED_ZONE="$HOSTED_ZONE" \
    --from-literal=RG_NAME="$RG_NAME" \
    --from-literal=SUBSCRIPTION_ID="$SUB_ID" \
    --from-literal=TENANT_ID="$TENANT_ID"
```
or using the yaml template:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
    # set a name of your choosing
    name:
    # use the namespace name in case you plan to deploy in a non-default one.
    # Otherwise you can set to default, or not use the next field altogether
    namespace:
data:
  CLIENT_ID:
  EMAIL_CERT:
  HOSTED_ZONE:
  RG_NAME:
  SUBSCRIPTION_ID:
  TENANT_ID:
```
##### AWS:
```sh
kubectl create secret generic $secret_name \
    --from-literal=EMAIL_CERT="$EMAIL_CERT" \
    --from-literal=ACCOUNT_ID="$ACCOUNT_ID" \
    --from-literal=REGION="$REGION" \
    --from-literal=ROLE_NAME="$ROLE_NAME"
```
or using the yaml template:
```yaml
apiVersion: v1
kind: Secret
metadata:
    # set a name of your choosing
    name:
    # use the namespace name in case you plan to deploy in a non-default one.
    # Otherwise you can set to default, or not use the next field altogether
    namespace:
data:
  EMAIL_CERT:
  ACCOUNT_ID:
  REGION:
  ROLE_NAME:
type: Opaque
```

### Copying existing secrets
If the secret(s) exist in another namespace, you can "copy" them with this command:
```sh
kubectl get secret $secretname  --namespace=$old_namespace -oyaml | grep -v '^\s*namespace:\s' | kubectl apply --namespace=$new_namespace -f -
```

### Values.yaml
Few conventions to begin with. Some nested field will be referred by a dot-path notation. An example would be:
```yaml
main:
  field: value
```
will be referenced as `main.field`.

In order to deploy a `yaml` file is needed to customize certain configurations for the FN to adapt to its new environment. A template that resembles the DRE deployment will be attached to the LastPass note.

Download it in your working folder (the one you're going to run the deployment command from, see below) and change values as needed.

If you want to use develop images, you can set
`backend.tag` for the flask backend
`keycloak.tag` for the keycloak service

e.g.
```yaml
keycloak:
  tag: 0.0.1-617710
```
will use `ghcr.io/aridhia-open-source/federated_keycloak:0.0.1-617710` in the statefulset.

__IMPORTANT NOTE__: If deploying on Azure AKS, set `ingress.on_aks` to `true`. This will make dedicated configuration active to run properly on that platform.

Once the secrets have been created use their names as follows:
#### db creds
```yaml
db:
  host: <host name>
  name: federated_node_db
  user: <DB username>
  secret:
    key: value
    name: <secret name here>
```

#### azure storage account
```yaml
storage:
  azure:
    secretName: <secret name here>
    shareName: files
```

### Deployment command
```sh
helm install federatednode federated-node/federated-node -f <custom_value.yaml>
```
If you don't want to install it in the default namespace:
```sh
helm install federatednode federated-node/federated-node -f <custom_value.yaml> --create-namespace --namespace=$namespace_name
```
