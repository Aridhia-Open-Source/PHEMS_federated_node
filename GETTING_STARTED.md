# Getting Started - Federated Node

### Assumptions
All users of the Federated Node need credentials to interact with it. These can be gathered from the `kc-secrets` secret in kubernetes.

```sh
kubectl get secret -n qcfederatednode kc-secrets -o json | jq -r '.data.KEYCLOAK_ADMIN_PASSWORD' | base64 -d
```
or save it in an env var
```sh
PASSWORD=$(kubectl get secret -n qcfederatednode kc-secrets -o json | jq -r '.data.KEYCLOAK_ADMIN_PASSWORD' | base64 -d)
```

Users who do don't have the required access should speak to the cluster administrator. 

It is reccommended saving the hostname in the `HOSTNAME` environment variable. This is the public url (defined in the values file used during deployment, under `nginx.host`). In this document we will refer to this in all of the API calls

In general if you want to know beforehand what all the endpoints do, or what their response is, visit `<HOSTNAME>/docs` on the public url set for your deployment.

## Login
```sh
TOKEN=$(curl --location "https://$HOSTNAME/login" \
    --header 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'username=admin' \
    --data-urlencode 'password="$PASSWORD"' | jq -r '.access_token')
```
where `HOSTNAME` is the public url (defined in the values file used during deployment, under `nginx.host`)

The response will look like:
```json
{
    "access_token": "eyJhbGciOiJIU...."
}
```

By "passing" this response to `jq` it will automatically saves the token inside the `TOKEN` environment variable.

This token will have a default lifetime of 30 days, and can be used for that time even if the cluster restarts.

## Create a dataset
This creates a link, or maps the coordinates to the database, for a dataset in the FN.

Only administrators can create one.

```sh
curl --location "https://$HOSTNAME/datasets/" \
    --header 'Content-Type: application/json' \
    --header "Authorization: $TOKEN" \
    --data '{
        "name": "",
        "host": "",
        "port": 5432,
        "username": "",
        "password": ""
    }'
```

In response you will get the dataset id


## List all datasets
```sh
curl --location "https://$HOSTNAME/datasets/" \
    --header 'Content-Type: application/json' \
    --header "Authorization: $TOKEN"
```

## Add dataset permission to a user
Only Administrators can trigger this.

If the user doesn't exist, they  will be created with a basic role. At present adminstrators cannot be created  via the API.

```sh
curl --location "https://$HOSTNAME/datasets/token_transfer" \
    --header 'Content-Type: application/json' \
    --header "Authorization: $TOKEN"
    --data-raw '{
        "title": "",
        "project_name": "",
        "requested_by": {
            "email": ""
        },
        "description": "",
        "proj_start": "2024-10-01",
        "proj_end": "2025-02-25",
        "dataset_id": 1
    }'
```

## Create a task/analysis
Only administrators or other approved users can trigger a task:
```
a```sh
curl --location "https://$HOSTNAME/tasks/" \
--header 'Content-Type: application/json' \
--header "Authorization: $TOKEN" \
--data '{
	"name": "",
	"executors": [
		{
			"image": "aridhia-open-source/rtest:latest"
		}
	],
	"tags": {
		"dataset_id": 1
	},
	"description": "First task ever!"
}'
```
