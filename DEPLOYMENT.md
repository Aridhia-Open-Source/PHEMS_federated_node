# Federated Node Deployment Instructions

### Prerequisite
The federated node is deployed as an Helm Chart, so helm should be installed in your system.

See their installation instructions [here](https://helm.sh/docs/intro/install/).

### Setup helm repo
Until v1.0 a set of credentials will need to be required to pull docker images and the helm chart. These credentials will be set in a shared note in LastPass, called `FN setup notes`.

Set the two env vars `$username` and `$password`, based on the note above.
```sh
helm repo add --username $username --password $token federated-node https://gitlab.com/api/v4/projects/aridhia%2Ffederated_node/packages/helm/stable
```
If you want to run a development chart
```sh
helm repo add --username $username --password $token federated-node https://gitlab.com/api/v4/projects/aridhia%2Ffederated_node/packages/helm/develop
```

Now you should be all set to pull the chart from gitLab.

### Pre-existing Secrets (optional)
In order to not store credentials in plain text within the `values.yaml` file, there is an option to pre-populate secrets in a safe matter.

The secrets to be created are:
- Db credentials for the FN webserver to use (not where the dataset is)
- ACR credentials (provided in the same LastPass note)
- Azure storage account credentials

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
    --from-literal=username=(echo $username | base64) \
    --from-literal=password=(echo $password | base64)
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
    --from-literal=value=(echo $password | base64)
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
    --from-literal=azurestorageaccountkey=(echo $accountkey | base64) \
    --from-literal=azurestorageaccountname=(echo $accountname | base64)
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
In order to deploy a `yaml` file is needed to customize certain configurations for the FN to adapt to its new environment. A template that resembles the DRE deployment will be attached to the LastPass note.

Download it in your working folder (the one you're going to run the deployment command from, see below) and change values as needed.

If you want to use develop images, you can set
`image.tag` for the flask backend
`keycloak.tag` for the keycloak service

e.g.
```yaml
keycloak:
  tag: 0.0.1-617710
```
will use `ghcr.io/arihdia-federated-node/federated_keycloak:0.0.1-617710` in the statefulset.

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
