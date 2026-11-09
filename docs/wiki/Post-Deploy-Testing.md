# Post-Deploy Testing

Use this guide to verify your Federated Node 2.x is healthy before you set up a project and hand it over to users. It checks the install only.


## 1. Check pod status

```sh
kubectl get pods -n federated-node
kubectl get pods -n keycloak
kubectl get jobs -A
```

Every pod should reach `Running`, and the `*-db-init` and `keycloak-realm-init` jobs should show `Completed`. The first start takes a few minutes while Keycloak and the databases initialise.

If anything is stuck, check its logs:

```sh
kubectl describe pod <pod> -n federated-node
kubectl logs <pod> -n federated-node
```


## 2. Set your hostname

All examples in this guide use `$FN_HOST`.

**If accessing via a public hostname:**
```sh
export FN_HOST=https://fn.your-institution.example.com
```

**If port-forwarding to nexus-api directly (no Traefik):**
```sh
kubectl port-forward -n federated-node service/nexus-api 5000:5000
export FN_HOST=http://localhost:5000
```


## 3. Health check

```sh
curl "$FN_HOST/health_check"
```

It returns `"status": "ok"` when nexus-api can reach Keycloak, and a 502 otherwise. If it stays at 502, give Keycloak a minute and retry, then check the Keycloak pod's logs.


## 4. Login

Log in as the first user, with the email from `firstUserSecret.email` and the password in the secret you created for it. `/login` takes form fields, not JSON, and returns a bearer token:

```sh
PASSWORD=$(kubectl get secret -n federated-node fn-first-user -o jsonpath='{.data.password}' | base64 -d)

TOKEN=$(curl --silent "$FN_HOST/login" \
    -F "username=admin@your-institution.example.com" \
    -F "password=$PASSWORD" | jq -r '.token')
```

The token lasts 8 hours (`POST /refresh_token` renews it). The Keycloak admin password, if you need it, is in the `kc-secrets` secret in the `keycloak` namespace.

Then check the node as a whole:

```sh
curl -sS "$FN_HOST/global/healthcheck" -H "Authorization: Bearer $TOKEN" | jq
```

A failing check shows in the body with a status of 200, never a 500, and never contains a secret value. On a new node with nothing registered yet, it has little to check.


## 5. Check Dagster

The Dagster UI has no login and no route, so reach it with a port-forward. It listens on port 80, so `3000:3000` fails:

```sh
kubectl port-forward -n federated-node svc/federatednode-dagster-webserver 3000:80
```

Open http://localhost:3000 and check that the code location loads with no error. Under **Automation** you should see twelve sensors, all stopped. That is how a new node starts, and it is correct for now.


## 6. Run the chart's own tests

```sh
helm test federatednode -n federated-node --logs
```

With `smoketests: true` in your values, the tests also create and delete real rows. The full list of checks for a node is the repo's [deploy and health checklist](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/QA/deploy-and-health.md).


## Next steps

- [Researcher guide](./Researcher-Guide): how a researcher asks for a task, once the project is enabled.
- [Operations](./Operations): looking after a running node.
