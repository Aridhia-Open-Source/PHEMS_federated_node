# Getting Started - Federated Node

### Assumptions
Before we start interacting with the Federated Node, it is important to have a set of credentials. These can be gathered from the `kc-secrets` secret in kubernetes.

```sh
kubectl get secret -n qcfederatednode kc-secrets -o json | jq -r '.data.KEYCLOAK_ADMIN_PASSWORD' | base64 -d
```
or save it in an env var
```sh
PASSWORD=$(kubectl get secret -n qcfederatednode kc-secrets -o json | jq -r '.data.KEYCLOAK_ADMIN_PASSWORD' | base64 -d)
```

Ask the cluster administrator, or the person who has performed the deployment in case you don't have direct access to it.

It is reccommended, for purely convenience purproses, to save the hostname in the `HOSTNAME` environment variable. This is the public url (defined in the values file used during deployment, under `nginx.host`). In this document we will refer to this in all of the API calls

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

This token will have a default lifetime of 30 days, and can be used without the need of creating a new one even if the cluster restarts.

## Create a dataset
It's not really creating data per se, just a link, or mapping the coordinates to the database in the FN.

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
Only Administrators can trigger this. Fill up the information as appropriate.

If the user doesn't exist, it will be created with a basic role. At the current time it is not allowed to create Administrators via this API.
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
Only administrators, and users who have been approved to access data can trigger one. Fill up the information as appropriate
```sh
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
