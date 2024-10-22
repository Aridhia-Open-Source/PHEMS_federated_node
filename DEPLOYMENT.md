# Federated Node Deployment Instructions

### Prerequisite
The federated node is deployed as an Helm Chart, so helm should be installed in your system.

See their installation instructions [here](https://helm.sh/docs/intro/install/).

### Setup helm repo
```sh
helm repo add federated-node https://gitlab.com/api/v4/projects/aridhia%2Ffederated-node/packages/helm/stable
```
If you want to run a development chart
```sh
helm repo add federated-node https://gitlab.com/api/v4/projects/aridhia%2Ffederated-node/packages/helm/develop
```

Now you should be all set to pull the chart from gitLab.

### Pre-existing Secrets (optional)
In order to not store credentials in plain text within the `values.yaml` file, there is an option to pre-populate secrets in a safe matter.

The secrets to be created are:
- Db credentials for the FN webserver to use (not where the dataset is)
- ACR credentials (for the basic ghcr.io repo, you can create a personal access token with the `repo` and `write:packages` permissions. Use the generated token as password, and your github username)
- Azure storage account credentials (if used)

If you plan to deploy on a dedicated namespace, create it manually first or the secrets creation will fail
```sh
kubectl create namespace <new namespace name>
```

__Please keep in mind that every secret value has to be a base64 encoded string.__ It can be achieved with the following command:
```sh
echo -n "value" | base64
```

#### Container Registries
The following examples aims to setup container registries (ACRs) credentials.

In general, to create a k8s secret you run a command like the following:
```sh
kubectl create secret generic $secret_name \
    --from-literal=username=$(echo -n $username | base64) \
    --from-literal=password=$(echo -n $password | base64)
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
  password:
  username:
type: Opaque
```

then you can apply this secret with the command:
```sh
kubectl apply -f file.yaml
```
replace file.yaml with the name of the file you created above.

#### Database
In case you want to set DB secrets the structure is slightly different:

```sh
kubectl create secret generic $secret_name \
    --from-literal=value=$(echo -n $password | base64)
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
```sh
kubectl create secret generic $secret_name \
    --from-literal=azurestorageaccountkey=$(echo -n $accountkey | base64) \
    --from-literal=azurestorageaccountname=$(echo -n $accountname | base64)
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

#### acrs
```yaml
acrs:
# env specific
  - url: .azurecr.io
    email: ''
    secret:
      name: <secret name here>
      userKey: username
      passKey: password
# from the lastpass note
  - url: ghcr.io
    secret:
      name: <secret name here>
      userKey: username
      passKey: password
    email: ''
```


### Deployment command
```sh
helm install federatednode federated-node/federated-node -f <custom_value.yaml>
```
If you don't want to install it in the default namespace:
```sh
helm install federatednode federated-node/federated-node -f <custom_value.yaml> --create-namespace --namespace=$namespace_name
```
