# Post-Deploy Testing

Use this guide to verify your Federated Node is healthy and fully functional before handing it over to users or setting up the Task Controller.


## 1. Check pod status

```sh
kubectl get pods -n federated-node
kubectl get pods -n keycloak
kubectl get pods -n tasks
```

All pods should reach `Running` status. Keycloak can take 1–2 minutes on first boot.

If anything is stuck, check its logs:

```sh
kubectl logs -n federated-node deployment/backend
kubectl logs -n keycloak statefulset/keycloak
```


## 2. Set your hostname

Set the FN hostname in an environment variable. All examples in this guide use `$FN_HOST`.

**If accessing via a public hostname:**
```sh
export FN_HOST=https://fn.your-institution.example.com
```

**If port-forwarding to the backend directly (no Traefik):**
```sh
kubectl port-forward -n federated-node service/backend 5000
export FN_HOST=http://localhost:5000
```

**If port-forwarding through Traefik:**
```sh
# Note: the service name includes your helm release name (federatednode)
kubectl port-forward -n federated-node service/federatednode-traefik 443:443
export FN_HOST=https://localhost
```


## 3. Health check

```sh
curl "$FN_HOST/health_check"
```

Expected response:

```json
{
    "status": "ok",
    "keycloak": true
}
```

If `keycloak` is `false`, Keycloak hasn't finished starting. Wait 30 seconds and retry. If it stays `false`, check Keycloak logs.


## 4. Login

If you configured `firstUserSecret`, use that email and password. Otherwise retrieve the auto-generated password:

```sh
PASSWORD=$(kubectl get secret -n federated-node kc-secrets -o json \
  | jq -r '.data.KEYCLOAK_ADMIN_PASSWORD' | base64 -d)
```

Log in and save the token:

```sh
TOKEN=$(curl --silent --location "$FN_HOST/login" \
    --header "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=admin@your-institution.example.com" \
    --data-urlencode "password=$PASSWORD" | jq -r '.token')

echo $TOKEN
```

You should see a JWT string. If you get an error, confirm Keycloak is healthy (step 3) and that the username/password are correct.

All subsequent API calls pass this token as `Authorization: Bearer $TOKEN`. Tokens are valid for 30 days by default.


## 5. Create a test dataset

A dataset registration tells the FN where your research database lives. The FN stores the connection details - it never copies or centralises the data.

```sh
curl --silent --location "$FN_HOST/datasets/" \
    --header 'Content-Type: application/json' \
    --header "Authorization: Bearer $TOKEN" \
    --data '{
        "name": "test-dataset",
        "host": "your-database-host.example.com",
        "port": 5432,
        "username": "db-user",
        "password": "db-password",
        "type": "postgres",
        "schema": "public"
    }' | jq .
```

The `type` field sets the database engine. Options: `postgres`, `mssql`, `mysql`, `oracle`, `mariadb`, and from v1.21.0 `duckdb` and `sqlite`. Defaults to `postgres` if omitted. See [Datasets](Datasets.md) for examples of each.

Expected response:

```json
{ "dataset_id": 1, "url": "https://<host>/datasets/test-dataset" }
```

Confirm it was saved:

```sh
curl --silent "$FN_HOST/datasets/" \
    --header "Authorization: Bearer $TOKEN" | jq .
```


## 6. Register a container registry and allowlist an image

The FN controls which images can run against your data via a registry allowlist. First register the registry:

```sh
curl --silent --location "$FN_HOST/registries/" \
    --header 'Content-Type: application/json' \
    --header "Authorization: Bearer $TOKEN" \
    --data '{
        "url": "ghcr.io/your-org",
        "username": "your-github-username",
        "password": "your-github-PAT"
    }' | jq .
```

Then allowlist a specific image (only needed if `federatedNode.enable_image_whitelist: true`):

```sh
curl --silent --location "$FN_HOST/containers" \
    --header 'Content-Type: application/json' \
    --header "Authorization: Bearer $TOKEN" \
    --data '{
        "name": "test-analysis",
        "registry": "ghcr.io/your-org",
        "tag": "1.0"
    }' | jq .
```

> **Note:** Image whitelisting is off by default (`federatedNode.enable_image_whitelist: false`). When off, any image from a registered registry can run. Enable it for tighter control in production.


## 7. Submit a test task

```sh
TASK=$(curl --silent --location "$FN_HOST/tasks/" \
    --header 'Content-Type: application/json' \
    --header "Authorization: Bearer $TOKEN" \
    --data '{
        "name": "smoke-test",
        "executors": [
            {
                "image": "ghcr.io/your-org/test-analysis:1.0"
            }
        ],
        "tags": {
            "dataset_id": 1
        },
        "description": "Post-deploy smoke test"
    }')

echo $TASK | jq .
TASK_ID=$(echo $TASK | jq -r '.task_id')
```

Watch the task pod appear in the tasks namespace:

```sh
kubectl get pods -n tasks
```

Check task status:

```sh
curl --silent "$FN_HOST/tasks/$TASK_ID" \
    --header "Authorization: Bearer $TOKEN" | jq '.status'
```


## 8. Retrieve results

Once status is `COMPLETE`:

```sh
curl --silent "$FN_HOST/tasks/$TASK_ID/results" \
    --header "Authorization: Bearer $TOKEN" \
    --output results.tar.gz

tar -tzf results.tar.gz
```

If `taskReview` is enabled in your values, an admin must approve results before they can be retrieved. See [Task Review](Task-Review.md).

> **Note:** The cleanup CronJob removes task results and related Kubernetes resources daily at noon, after `cleanupTime` days (default: 3). Retrieve results before then.


## All checks passed?

Your Federated Node is working. Next steps:

- Set up users and dataset permissions → [User Roles](User-Roles.md) and [Using the API](Using-The-API.md)
- Enable the results review workflow → [Task Review](Task-Review.md)
- Deploy the Task Controller for outbound-only mode → [Task Controller Overview](https://github.com/Aridhia-Open-Source/federated-node-task-controller/wiki)
- Build analytics containers → [Analytics Container Development](Analytics-Container-Development.md)
