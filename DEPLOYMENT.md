# Federated Node Deployment

How to run the Federated Node (FN) on your own machine, and how to deploy it to a production cluster.

This guide is for the 2.x chart (the Dagster line). Once the node is up, set up your first project with [MANAGEMENT.md](MANAGEMENT.md).

The [wiki](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki) has a deploy page per platform: [Azure](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-Azure), [AWS](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-AWS), [GCP](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-GCP) and [On-Premises](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-On-Premises). Follow the page for your provider together with [Deploy-Core](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-Core). The platform pages are marked untested; where one disagrees with this page, follow this page.

- [What gets deployed](#what-gets-deployed)
- [Run it locally](#run-it-locally)
- [Deploy to production](#deploy-to-production)
- [Upgrade, uninstall, reinstall](#upgrade-uninstall-reinstall)
- [Where versions come from](#where-versions-come-from)

## What gets deployed

One Helm chart, `k8s/federated-node`, installs:

| Part | Namespace | Notes |
|---|---|---|
| nexus-api (FastAPI) | release namespace | The record and the rules. Port 5000 |
| Dagster webserver, daemon, code server | release namespace | Runs the sensors and the task and delivery jobs. The UI has no login: never expose it |
| Keycloak | `keycloak` | Logins and roles. Reached at `https://<host>/keycloak` |
| Postgres | release namespace | Only with `create_db_deployment: true` (local development). In production you bring your own server |
| Traefik + Gateway API routes | release namespace | Optional subchart. Serves nexus-api and Keycloak on `host` |
| cert-manager | `fn-certmanager` | Optional subchart, for certificate renewal |
| Gitea | release namespace | Optional, `gitea.enabled`. A git host for development only |
| Task pods | `tasks` | Created per task by Dagster. A NetworkPolicy blocks the public internet: they reach cluster DNS, private address ranges and listed databases |
| Quarantine | `fn-quarantine` | Holds the value of a disabled secret |

The components and the network between them are drawn in [docs/architecture/flows.md](docs/architecture/flows.md#components-and-network).

## Run it locally

The local setup is a [kind](https://kind.sigs.k8s.io/) cluster, a local image registry, the chart installed with development values, and [Tilt](https://tilt.dev/) for live reload.

### You need

- Docker
- `kind`, `kubectl`, `helm` (v3), `tilt`, `jq`
- [mise](https://mise.jdx.dev/): install it and activate it in your shell (`mise run` works without activation; activating adds automatic tool and venv switching on `cd`), then run `mise run setup` and `mise run init-conf`.
- Personal overrides go in `mise.local.toml` (gitignored).
- Or use the dev container instead (see [Dev container](#dev-container) below).
- Python 3.12+ and `pipx`, for `fncli` (the ops tool, see [MANAGEMENT.md](MANAGEMENT.md))

### First time

Run these from the repo root.

1. Create your two local config files. Both are gitignored.

   ```bash
   cp .dev.env.example .dev.env
   cp k8s/federated-node/dev.example.values.yml k8s/federated-node/dev.values.yaml
   ```

2. Edit `.dev.env`. Set `KEYCLOAK_FIRST_USER_EMAIL` and `KEYCLOAK_FIRST_USER_PASSWORD`: that is your admin login for the API. `NAMESPACE` must match the `db.host` in `dev.values.yaml` (`db.<namespace>.svc`). The file explains every other variable.

3. Fetch the chart's subcharts. `charts/` is gitignored, so a fresh checkout has none and Helm refuses to render.

   ```bash
   mise run helm-deps
   ```

4. Create the cluster and the registries.

   ```bash
   mise run cluster-up
   ```

   This starts a registry at `localhost:5001` (your images) and two pull-through mirrors (`localhost:5002` Docker Hub, `localhost:5003` GHCR), then a kind cluster named `fn` with its context `kind-fn`. Local volumes live in `~/.fn/data` (set `FN_DATA_DIR` to move it; the cluster must be recreated for that to take effect).

5. Build the images and install the chart.

   ```bash
   mise run deploy
   ```

   It claims the dev cluster (see [one owner at a time](#one-owner-at-a-time)), renders the chart as a check, prepares the host directories, builds every image into `localhost:5001` (`docker-bake.hcl`; `mise run image --target nexus-api-fn` rebuilds one), creates the namespace and the `keycloak-first-user` secret, then runs `helm install` (up to 10 minutes). At the end it prints the database passwords the chart generated.

6. Start Tilt for the port-forwards and live reload.

   ```bash
   tilt up
   ```

   | What | Where |
   |---|---|
   | Backend API | http://localhost:5000 (docs at `/docs`) |
   | Dagster UI | http://localhost:3000 |
   | Gitea | http://localhost:4000 |
   | Keycloak | http://localhost:8080 |
   | Postgres | `localhost:5432` |
   | Tilt dashboard | http://localhost:10350 |

   The `dagster-reload` resource prints this list in the Tilt log once the Dagster code location has loaded, and again after each reload.

7. Check it works. Log in with the first user. `/login` takes form fields, not JSON, and returns a bearer token.

   ```bash
   source .dev.env
   curl -sS -X POST localhost:5000/login \
     -F "username=$KEYCLOAK_FIRST_USER_EMAIL" \
     -F "password=$KEYCLOAK_FIRST_USER_PASSWORD" | jq -r .token
   ```

8. Build a working project and watch a pull request run end to end. `fncli demo` does it one confirmed step at a time. Install and usage are in [MANAGEMENT.md](MANAGEMENT.md#using-fncli).

### Day to day

Tilt watches the code and updates the running pods. You do not redeploy for code changes.

| You change | What happens |
|---|---|
| `nexus/api/app/`, `dagster/app/` | Files are synced and the process restarts. For Dagster, `dagster-reload` then reloads the code location once the new code server is serving |
| `dagster/fncli/`, `dagster/app/tests/`, docs under `dagster/` | Nothing: the code server and run pods don't use them |
| `requirements.txt`, `setup.py`, `alembic.ini`, migrations | The image is rebuilt |
| The chart (`k8s/federated-node`) | Run `mise run deploy` (helm upgrade, then restarts the app deployments) |

| Task | Command |
|---|---|
| Stop or open Tilt | `tilt down`, `tilt open` |
| Rebuild one service | `tilt trigger nexus-api` |
| Read the generated database passwords | `mise run show-db-passwords` |
| Serve every docs version with the dropdown and live reload | `mise run docs` (`--port 8001`) |
| Serve one docs version with live reload | `mise run docs --version 2.x` |
| Lint and render the chart without a cluster | `mise run helm-lint && mise run helm-template` |
| Chart unit tests | `mise run helm-tests` |
| Dagster tests, pylint | `mise run tests-dagster`, `mise run pylint`, `mise run pylint-dagster` |
| Remove the release and its data, keep the cluster | `mise run teardown` |
| Start completely again (teardown, new cluster, deploy) | `mise run teardown && mise run cluster-down && mise run cluster-up && mise run deploy` |
| Delete the cluster, keep the registries | `mise run cluster-down` |

More Tilt detail is in [.tilt/TILT_QUICKSTART.md](.tilt/TILT_QUICKSTART.md).

### Every task, and what replaced make

`mise tasks` lists them all (it replaces `make help`). Run any of them from the repo root with `mise run <task>`. Arguments are `--flags`; nothing is passed as `NAME=value`. Task names use hyphens where the make targets used underscores.

| What it does | Old (make) | New (mise) |
|---|---|---|
| List the tasks | `make help` | `mise tasks` |
| Install the pinned tools and both virtualenvs | (manual) | `mise run setup` |
| Create `.dev.env` and `dev.values.yaml` | `make init-conf` | `mise run init-conf` |
| Lint the Dockerfiles | `make hadolint` | `mise run hadolint` |
| Lint nexus-api | `make pylint` | `mise run pylint` |
| Lint Dagster | `make pylint_dagster` | `mise run pylint-dagster` |
| Run the Dagster tests the way CI does | `make tests_dagster` | `mise run tests-dagster` |
| Run the chart's unit tests | `make helm_tests` | `mise run helm-tests` |
| Build the chart's subcharts | `make helm_deps` | `mise run helm-deps` |
| Lint the chart (builds subcharts first) | `make helm_lint` | `mise run helm-lint` |
| Render the chart with no cluster (builds subcharts first) | `make helm_template` | `mise run helm-template` |
| Print the generated database passwords | `make show-db-passwords` | `mise run show-db-passwords` |
| Lock a component's requirements | `make pip-compile DIR=nexus/api` | `mise run pip-compile --dir nexus/api` |
| ...to another file | `make pip-compile DIR=nexus/api OUT=requirements-dev.txt` | `mise run pip-compile --dir nexus/api --out requirements-dev.txt` |
| ...with extra pip-compile flags | `make pip-compile DIR=nexus/api ARGS="--upgrade"` | `mise run pip-compile --dir nexus/api -- --upgrade` |
| Build and push every image | `make images` | `mise run images` |
| Build and push one image | `make image NAME=nexus-api-fn` | `mise run image --target nexus-api-fn` |
| ...and restart the deployments | `make image-reload NAME=nexus-api-fn` | `mise run image-reload --target nexus-api-fn` |
| Build the release images locally | `make images-release TAG=1.2.3` | `mise run images-release --tag 1.2.3` |
| Rebuild the Dagster and nexus-api images, restart their pods | `make reload_app` | `mise run reload-app` |
| Start the kind cluster and registries | `make cluster-up` | `mise run cluster-up` |
| Delete the cluster, keep the registries | `make cluster-down` | `mise run cluster-down` |
| ...and delete the registries | `make cluster-down ARGS=--remove-registries` | `mise run cluster-down --remove-registries` |
| Build images and install or upgrade the release | `make deploy` | `mise run deploy` |
| ...taking the cluster over from another worktree | `make deploy FORCE_OWNER=1` | `mise run deploy --force-owner` |
| Remove the release and its data | `make teardown` | `mise run teardown` |
| Port-forward the node's services (without Tilt) | `make portfwd` | `mise run portfwd` |
| Show which worktree owns the cluster | `make deploy-owner` | `mise run deploy-owner` |
| New sibling worktree | `make worktree NAME=wt-foo BRANCH=feature/foo BASE=main` | `mise run worktree --name wt-foo --branch feature/foo --base main` |

`--force-owner` also works on `cluster-down`, and `--base` is optional (it defaults to `HEAD`).

### One owner at a time

There is one dev cluster and one worktree owns it. `mise run deploy` claims it, `mise run teardown` releases it. A deploy from another worktree fails while it is owned: tear down from the owner, or rerun with `mise run deploy --force-owner` to take over. `mise run deploy-owner` shows who owns it.

To start another worktree, run `mise run worktree --name <dir> --branch <branch> [--base <ref>]` from this checkout. It creates `../<dir>` and copies over the gitignored `.dev.env`, `dev.values.yaml` and other `.env`/`.yaml` files; then `cd ../<dir> && mise run helm-deps && mise run deploy`.

### Development database passwords

The chart generates every database password and reuses it on each upgrade, so `.dev.env` holds none. Read them with `mise run show-db-passwords`, or one at a time:

```bash
kubectl get secret fn-nexus-db -n fn -o jsonpath='{.data.password}' | base64 -d
```

### Loading real sample data

Experiments, each with its own seeded database, run from their own release in the `experiments` namespace. See [experiments/README.md](experiments/README.md).

### Dev container

An optional alternative to installing the tools on your machine. Open the repo in VS Code and choose **Reopen in Container**; on first create it runs `mise run setup`.

- It uses your machine's Docker (socket) and kind cluster, and shares its network. It reads your `~/.kube/config` live (read-only), so a recreated cluster works without a restart, and keeps its own small overlay that makes `fn` the default namespace for `kind-fn`; your own kubeconfig is never changed, so `kubectl`, `kind` and Tilt work against the same cluster.
- Port-forwards from Tilt land on your machine's `localhost` (nexus-api on `localhost:5000` as usual). Run Tilt in one place at a time, or the ports clash.
- It mounts the checkout's parent folder at the same path as on your machine (and `~/.fn`, the local PV data, likewise). Your Docker resolves volume paths on your machine, so the scripts' `docker run -v "$(pwd)":...` and `FN_DATA_DIR` work unchanged, and the cluster owner recorded inside matches the one recorded outside.
- Git works in it for the main repo and for worktrees in the same parent folder (the layout `mise run worktree` creates). A worktree elsewhere has no git inside the container, because its `.git` points at a main repo the container cannot see.
- After changing `.devcontainer/devcontainer.json`, rebuild the container (**Dev Containers: Rebuild Container**).
- Its venvs live in the container (`/home/vscode/venvs/`), not in the checkout, so they don't clash with yours.
- Installed tools are kept in the `fn-mise-data` volume, so rebuilds and other worktrees' containers reuse them.
- The cluster ownership rules apply inside it as well: it's the same cluster.

## Deploy to production

Production is the same chart with different values: an external Postgres, Traefik and TLS on a real hostname, shared storage, and no development switches (`local_development`, `create_db_deployment`, Gitea, local images).

### 1. You need

- A Kubernetes cluster, with a node pool sized for the base pods plus the analytics task pods. The wiki's baseline is 4 vCPU / 8 GB per node, and Dagster adds to it. Tested on AKS, EKS, GKE and RKE2.
- `kubectl` and `helm` (v3) pointing at it, and `jq`.
- A PostgreSQL server the cluster can reach, with an admin login. The FN needs its own databases on it, not your research data. The chart creates them (see [Databases](#databases)).
- A hostname for the node, and a TLS certificate for it (or cert-manager).
- `ReadWriteMany` shared storage: Azure Files, AWS EFS, NFS, or a local path (single node only). Dagster task pods and the run pods write results to the same volume, so ReadWriteOnce disks do not work.
- A CNI that enforces NetworkPolicy (Calico, Cilium or your cloud's network policy add-on; kind's default does). By default the chart denies a task pod all ingress and all egress but DNS and private address ranges, and on a CNI that ignores NetworkPolicy that does nothing.
- Outbound HTTPS to `ghcr.io` (images), to your git host (GitHub: `api.github.com`) and to wherever your analytics images live.

### 2. Install the CRDs, once per cluster

Traefik and the routes need the Gateway API and Traefik CRDs. The chart refuses to install without them (when `traefik.enabled` is true). From the repo root:

```bash
./scripts/gateway-api-installer.sh
```

It applies both sets with server-side apply. The Gateway API version defaults to 1.4.0 (`./scripts/gateway-api-installer.sh 1.4.0`). Skip this only if you set `traefik.enabled: false` and bring your own ingress.

### 3. Get the chart

```bash
helm repo add federated-node https://aridhia-open-source.github.io/PHEMS_federated_node
helm repo update
helm search repo federated-node --devel --versions
```

The 2.x line is published as pre-releases, so it only shows with `--devel`. Pick the newest `2.0.0-...` entry the search lists and pin it with `--version` in step 6. At the time of writing the index lists `2.0.0-dagster-alpha.1`; the `dagster-main` branch builds `2.0.0-dagster-beta.N` ([Where versions come from](#where-versions-come-from)), which appears once that build is published.

Leave `default_image_tag` unset. Every image tag then follows the chart's `appVersion`, so the chart and the images always move together. Set it only to hold the images at an older build.

### 4. Create the namespace and the secrets you must provide

```bash
kubectl create namespace federated-node
```

The chart creates every database password, the Keycloak credentials and the Dagster login for you, and puts them in the namespaces that need them. These are the ones it cannot invent:

| Secret | Key | When | What it is |
|---|---|---|---|
| `postgres-superuser` | `password` | Postgres is external and `db.manageRolesAndDatabases` is true (the default) | Password of `db.superuser` on your server |
| the secret named by `firstUserSecret.name` | the key in `firstUserSecret.passKey` | Always | Password of the first admin user. The chart copies it to the Keycloak namespace |
| `tls` (or the name in `tls.secretName`) | `tls.crt`, `tls.key` | No cert-manager | The certificate for `host`, full chain |
| the Azure storage secret | `azurestorageaccountname`, `azurestorageaccountkey` | `storage.azure` | The chart copies it to the tasks namespace |

```bash
kubectl create secret generic postgres-superuser -n federated-node \
  --from-literal=password='<postgres admin password>'

kubectl create secret generic fn-first-user -n federated-node \
  --from-literal=password='<admin password you will log in with>'

kubectl create secret tls tls -n federated-node \
  --cert server.crt --key server.key
```

Special characters (`"`, `%`) break `--from-literal` in some shells. Use a YAML manifest with a base64 value if that bites.

Git and dataset credentials are **not** Helm secrets: you register them through the API after the install, as global Secrets ([MANAGEMENT.md](MANAGEMENT.md)).

### 5. Write your values file

Start from the example below, then add the storage block for your platform. It renders cleanly with `helm template`.

```yaml
# The public hostname. Needs a DNS record pointing at Traefik, and a certificate.
host: fn.your-institution.example.com

# Names this node (hospital) in the results it delivers (run.json, node.id). Required.
nodeId: your-institution

# One external Postgres server shared by every component.
db:
  host: &dbHost postgres.your-institution.example.com
  port: 5432
  # The admin login the *-db-init jobs use to create each database and role.
  # Managed Postgres has no role called "postgres" (Azure, RDS, Cloud SQL): set yours.
  superuser: fn_admin
  enforceSSL: true
  secret:
    name: postgres-superuser     # the secret from step 4
    key: password

# The first admin user. Its password is the secret from step 4.
firstUserSecret:
  name: fn-first-user
  passKey: password
  email: admin@your-institution.example.com
  firstName: Admin
  lastName: User

# Shared storage for results. Use ONE of azure, aws, nfs, local (see Storage below).
storage:
  capacity: 50Gi
  nfs:
    provisioner: nfs.csi.k8s.io
    url: 192.168.1.100
    path: /exports/federated-node

# Ingress. The chart's own Traefik, with the Gateway API.
traefik:
  enabled: true

tls:
  secretName: tls

# Origins allowed to call the API from a browser (CSP).
integrations:
  domains:
    - https://fn.your-institution.example.com

# Dagster is off by default and has to be switched on.
dagster:
  enabled: true
  postgresql:
    # Must equal db.host. Helm cannot template a subchart value, so it is written
    # twice (the anchor keeps them together). The chart fails to render if they differ.
    postgresqlHost: *dbHost
    # Needed when db.enforceSSL is true, and the chart insists on it:
    postgresqlParams:
      sslmode: require
```

Things that are easy to get wrong:

- **Do not copy values from `dev.values.yaml`.** `local_development`, `create_db_deployment`, `gitea`, the `localhost:5001` images and `fnDagster.sensors.minIntervalSeconds: 5` are for development only.
- **`fnDagster.db` is removed** and the chart fails if you set it. Dagster's database name and user come from `dagster.postgresql.postgresqlDatabase` and `postgresqlUsername`.
- **`namespaces` lives under `global`** (`global.namespaces.keycloak`, `.tasks`, `.quarantine`). A top-level `namespaces` fails the render.
- **Datasets** are not configured here. Register them through the API (`/global/datasets`). For a development dataset database, see [experiments/README.md](experiments/README.md).
- Optional: `smoketests: true` lets `helm test` create and delete real rows.

Every value, with comments, is in [k8s/federated-node/values.yaml](k8s/federated-node/values.yaml), and the chart's own README is [k8s/federated-node/README.md](k8s/federated-node/README.md).

#### Storage

Set exactly one backend under `storage`. The same volume class is used for task results and for Dagster's artifacts.

| Platform | Values | Also needs |
|---|---|---|
| Azure Files (AKS) | `on_aks: true`, `storage.azure.secretName`, `storage.azure.shareName` | The file share exists already, plus the storage secret |
| AWS EFS (EKS) | `on_eks: true`, `storage.aws.fileSystemId`, optional `accessPointId` | The EFS CSI driver |
| NFS | `storage.nfs.url`, `.path`, `.provisioner` | The export is writable by uid 1000: `chown 1000:1000` and `chmod 775` |
| Local path | `storage.local.path`, `.dbpath`, `.artifacts` | Single node only; the pods are pinned to the node that holds the data |

Set `storage.nfs.provisioner` (for example `nfs.csi.k8s.io`) even without that driver installed: the chart writes it into the artifacts StorageClass, which is invalid empty. The wiki has a full walk-through per platform: [Azure](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-Azure), [AWS](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-AWS), [GCP](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-GCP) and [on-premises](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-On-Premises) (MetalLB or NodePort for Traefik, an existing ingress controller, pod security labels). Follow the page for your provider together with [Deploy-Core](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-Core).

#### TLS

Either create the `tls` secret yourself (step 4), or let cert-manager renew it: `cert-manager.enabled: true` plus `certs.azure.*` or `certs.aws` for DNS-01. For another CA, run cert-manager yourself and point `tls.secretName` at the secret it produces.

#### Databases

By default the chart manages the databases: three init jobs connect as `db.superuser` and create `fn_nexus`, `keycloak_db` and `dagster` with their own roles and generated passwords. Re-running them is harmless.

If a DBA owns the databases and you have no admin login, set `db.manageRolesAndDatabases: false`. The chart then needs no superuser, creates nothing, and each role's password becomes a secret you supply. Install once and it prints the exact SQL and `kubectl` commands for your names. A `db-check` hook verifies the roles before anything else installs.

For ArgoCD, `helm diff`, External Secrets or Vault, set `db.createPasswordSecrets: false` and let that tool own the password secrets. The chart reads them at runtime and never needs the value at render time.

### 6. Install

Check the file renders first. This needs no cluster:

```bash
helm template federatednode federated-node/federated-node \
  --devel --version <VERSION> -f values.yaml --namespace federated-node > /dev/null
```

Then install. The release name is `federatednode` throughout the docs, and some service names derive from it (`federatednode-dagster-webserver`), so keep it.

```bash
helm upgrade --install federatednode federated-node/federated-node \
  --devel --version <VERSION> \
  -f values.yaml \
  --namespace federated-node \
  --timeout 15m
```

The install reads the live cluster, so missing CRDs and missing secrets fail it at the start with a message that says what to create. Fix it and run the same command again.

### 7. Check it

```bash
kubectl get pods -n federated-node
kubectl get pods -n keycloak
kubectl get jobs -A
```

Expect every pod `Running` and the `*-db-init` and `keycloak-realm-init` jobs `Completed`. The first start takes a few minutes while Keycloak and the databases initialise.

Then:

1. `curl https://<host>/health_check`. It returns `"status": "ok"` when the backend can reach Keycloak (502 otherwise).
2. Log in as the first user (`POST /login`, form fields `username` and `password`, as in the [local check](#first-time)).
3. Open the Dagster UI through a port-forward and check the code location loads with no error:

   ```bash
   kubectl port-forward -n federated-node svc/federatednode-dagster-webserver 3000:80
   ```

   Then browse to http://localhost:3000. It listens on port 80, so `3000:3000` fails.
4. Run the chart's own tests: `helm test federatednode -n federated-node --logs`.
5. Work through [project/QA/deploy-and-health.md](project/QA/deploy-and-health.md) for the full list.

All Dagster sensors start **stopped**. Nothing is polled and no task runs until you start them, after the first project is set up ([MANAGEMENT.md](MANAGEMENT.md#start-the-sensors)).

> **Never publish the Dagster UI.** It has no login of its own. Anyone who can reach it can start, cancel and read runs. The chart creates no route for it on purpose: reach it with a port-forward, and treat that access as cluster access.

Useful reads after install:

```bash
# Passwords the chart generated (fn_nexus, keycloak, dagster roles)
kubectl get secret -A -l federatednode.com/generated-password=true

# Keycloak admin password
kubectl get secret kc-secrets -n keycloak -o jsonpath='{.data.KEYCLOAK_ADMIN_PASSWORD}' | base64 -d
```

### 8. Cluster hardening

The FN pods run non-root, with no privilege escalation and all capabilities dropped. They fit `restricted` Pod Security Standards. The `tasks` namespace runs whatever analytics images researchers supply, so use `baseline` there unless you control them all:

```bash
kubectl label namespace federated-node pod-security.kubernetes.io/enforce=restricted
kubectl label namespace keycloak       pod-security.kubernetes.io/enforce=restricted
kubectl label namespace tasks          pod-security.kubernetes.io/enforce=baseline
```

The chart creates a `ClusterRole` for the backend (pods, PVs, PVCs, jobs, secrets: it creates storage and task pods per task), so the user running `helm install` must be allowed to create cluster roles. The chart also creates a NetworkPolicy in the tasks namespace (`taskNetworkPolicy.enabled`, on by default): no ingress, and no public internet for task pods. Egress goes only to cluster DNS, to the private ranges in `taskNetworkPolicy.privateEgress` (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` by default, so in-cluster and private-network databases need no listing) and to the rules in `taskNetworkPolicy.datasetEgress` ([ADR 0022](project/decisions/0022-task-isolation.md)). A database on a public address (e.g. an Azure SQL public endpoint) must be listed in `datasetEgress`, or a task that needs it times out on connect. Narrow `privateEgress` to your own ranges, or set `taskNetworkPolicy.enabled: false` to manage policies on the tasks namespace yourself. DNS lookups still go through cluster DNS, so low-bandwidth DNS tunnelling remains possible. The tasks namespace must hold nothing but task pods: the chart refuses to render if `global.namespaces.tasks` is the release or Keycloak namespace.

With the same switch the node's own services refuse the tasks namespace, and Postgres, nexus-ui, Traefik and Keycloak get no public internet (cluster DNS, cluster pods and `privateEgress` only; [ADR 0022](project/decisions/0022-task-isolation.md)). Add a public Kubernetes API server address to `taskNetworkPolicy.privateEgress` so Traefik can read its routes, and set `keycloak.allowExternalEgress: true` for an external identity provider or a database on a public address.

## Upgrade, uninstall, reinstall

**Upgrade** with the same command as the install and a new `--version`. Passwords are reused, hook job names carry a hash so an image change does not fail on an immutable Job, and nexus-api applies database migrations itself (an init container runs `alembic upgrade head` before it starts).

```bash
helm repo update
helm upgrade --install federatednode federated-node/federated-node \
  --devel --version <NEW_VERSION> -f values.yaml -n federated-node --timeout 15m
```

Keycloak's platform credentials stay put across upgrades. To rotate them on purpose, raise `keycloak.credentialGeneration` by one, or set `keycloak.credentialRotation.enabled: true` for a monthly rotation.

**Uninstall** with `helm uninstall federatednode -n federated-node`. Helm does not remove what the hooks created: the generated password secrets (label `federatednode.com/generated-password=true`), the init jobs, the dataset credential secrets the backend wrote, and the data behind the Postgres volume if the chart ran the database.

**Reinstall onto the same external database server** works: the init jobs set each role's password to the newly generated one (`ALTER ROLE`), and the databases and their data are still there. Drop the databases first if you want a clean start.

**Reinstall with the chart's own Postgres** (`create_db_deployment: true`, development) is the exception. Postgres only reads its password when it first creates the data directory, so the data and the superuser secret go together: keep both or neither. If you delete only the secret, the install stops with a "stale postgres data" message that lists the two ways out.

For a throwaway development cluster, `mise run teardown` does all of this for you. Never run it against production: it deletes the namespaces and the data.

## Where versions come from

CI builds the images and packages the chart on every push, and the build decides the version suffix from the branch:

| Branch | Chart and image version | Use |
|---|---|---|
| a release tag | `2.0.0` | Production |
| `main` | `2.0.0-rc.N` | Release candidate |
| `develop` | `2.0.0-beta.N` | Integration |
| `dagster-main` | `2.0.0-dagster-beta.N` | The Dagster line before it joins `main` |
| `dagster-develop` | `2.0.0-dagster-alpha.N` | Earliest builds of that line |
| a pull request | `2.0.0-pr.<number>.g<sha>` | Review only |

`N` counts merges since the chart version last changed. A release is cut by running the **Create Release** workflow, which bumps `Chart.yaml`. The release job retags the images `main` already built for that commit.

The wiki's older `1.x` chart versions are the previous, non-Dagster line. Do not mix a 1.x values file with a 2.x chart.
