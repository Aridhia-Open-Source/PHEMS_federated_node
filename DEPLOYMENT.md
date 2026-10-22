# Federated Node Deployment

How to run the Federated Node (FN) on your own machine, and how to deploy it to a production cluster.

This guide is for the 2.x chart (the Dagster line). Once the node is up, set up your first project with [MANAGEMENT.md](MANAGEMENT.md).

The [wiki](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki) still has useful platform pages (Azure, AWS, GCP, on-premises storage and TLS). But its **Deploy: Core** page describes the 1.x chart (a single `db.name`, a `fn-db-secret` you create, a Postgres you provide). Where the wiki and this page disagree, follow this page.

- [What gets deployed](#what-gets-deployed)
- [Run it locally](#run-it-locally)
- [Deploy to production](#deploy-to-production)
- [Upgrade, uninstall, reinstall](#upgrade-uninstall-reinstall)
- [Where versions come from](#where-versions-come-from)

## What gets deployed

One Helm chart, `k8s/federated-node`, installs:

| Part | Namespace | Notes |
|---|---|---|
| Backend (Flask API) | release namespace | The record and the rules. Port 5000 |
| Dagster webserver, daemon, code server | release namespace | Runs the sensors and the task and delivery jobs. The UI has no login: never expose it |
| Keycloak | `keycloak` | Logins and roles. Reached at `https://<host>/keycloak` |
| Postgres | release namespace | Only with `create_db_deployment: true` (local development). In production you bring your own server |
| Traefik + Gateway API routes | release namespace | Optional subchart. Serves the backend and Keycloak on `host` |
| cert-manager | `fn-certmanager` | Optional subchart, for certificate renewal |
| Gitea | release namespace | Optional, `gitea.enabled`. A git host for development only |
| Task pods | `tasks` | Created per task by Dagster |
| Quarantine | `fn-quarantine` | Holds the value of a disabled secret |

The components and the network between them are drawn in [docs/architecture/flows.md](docs/architecture/flows.md#components-and-network).

## Run it locally

The local setup is a [kind](https://kind.sigs.k8s.io/) cluster, a local image registry, the chart installed with development values, and [Tilt](https://tilt.dev/) for live reload.

### One step

On Debian 13 or Ubuntu 24.04 and later, with Docker working (`docker info` without sudo):

```bash
./scripts/install-dev.sh      # or: make dev-install
```

It installs everything below, creates the config files with a generated first-user password, and runs every step of [First time](#first-time) up to Tilt. It ends with a healthcheck that lists each service's address. You can rerun it safely: anything already done is skipped. The log is in `~/.fn/install.log`.

To try it without touching your machine, `make sandbox up` runs it in a throwaway Debian container with its own Docker. `make sandbox shell` opens a shell in there, `SANDBOX=1 make <target>` runs any make target in there, and `make sandbox down` removes it. Edits to `webserver/` and `dagster/` live-reload in the sandbox too. See `scripts/sandbox.sh`.

### You need

- Docker
- `kind`, `kubectl`, `helm` (v3), `tilt`, `jq`
- Python 3.12+ and `pipx`, for `fncli` (the ops tool, see [MANAGEMENT.md](MANAGEMENT.md))

### First time

Run these from the repo root.

1. Create your two local config files. Both are gitignored.

   ```bash
   cp .dev.env.example .dev.env
   cp k8s/federated-node/dev.example.values.yml k8s/federated-node/dev.values.yaml
   ```

2. Edit `.dev.env`. Set `KEYCLOAK_FIRST_USER_EMAIL` and `KEYCLOAK_FIRST_USER_PASSWORD`: that is your admin login for the API. `NAMESPACE` must match the `db.host` and `datasetDb.host` in `dev.values.yaml` (`db.<namespace>.svc`), and `DOCKER_TAG` must match the tag in the values file. The file explains every other variable.

3. Fetch the chart's subcharts. `charts/` is gitignored, so a fresh checkout has none and Helm refuses to render.

   ```bash
   make helm_deps
   ```

4. Create the cluster and the registries.

   ```bash
   make cluster up
   ```

   This starts a registry at `localhost:5001` (your images) and two pull-through mirrors (`localhost:5002` Docker Hub, `localhost:5003` GHCR), then a kind cluster named `fn` with its context `kind-fn`. Local volumes live in `~/.fn/data` (set `FN_DATA_DIR` to move it; the cluster must be recreated for that to take effect).

5. Build the images and install the chart.

   ```bash
   make deploy
   ```

   It claims the dev cluster (see [one owner at a time](#one-owner-at-a-time)), renders the chart as a check, prepares the host directories, builds every image into `localhost:5001`, creates the namespace and the `keycloak-first-user` secret, then runs `helm install` (up to 10 minutes). At the end it prints the database passwords the chart generated.

6. Start Tilt for the port-forwards and live reload.

   ```bash
   tilt up
   ```

   | What | Where |
   |---|---|
   | Backend API | http://localhost:5000 |
   | Dagster UI | http://localhost:3000 |
   | Gitea | http://localhost:4000 |
   | Keycloak | http://localhost:8080 |
   | Postgres | `localhost:5432` |
   | Tilt dashboard | http://localhost:10350 |

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
| `webserver/app/`, `dagster/app/` | Files are synced and the process restarts |
| `requirements.txt`, `setup.py`, `alembic.ini`, migrations | The image is rebuilt |
| The chart (`k8s/federated-node`) | Run `make upgrade` (helm upgrade, then restarts the app deployments) |

| Task | Command |
|---|---|
| Stop or open Tilt | `make tilt-down`, `make tilt-open` |
| Rebuild one service | `tilt trigger backend` |
| Read the generated database passwords | `make show-db-passwords` |
| Lint and render the chart without a cluster | `make helm_lint helm_template` |
| Chart unit tests | `make helm_tests` |
| Dagster tests, pylint | `make tests_dagster`, `make pylint`, `make pylint_dagster` |
| Remove the release and its data, keep the cluster | `make teardown` |
| Start completely again (teardown, new cluster, deploy) | `make nuke` |
| Delete the cluster, keep the registries | `make cluster down` |

More Tilt detail is in [.tilt/TILT_QUICKSTART.md](.tilt/TILT_QUICKSTART.md).

### Behind a TLS-intercepting proxy

Both are optional dev tooling and do nothing when unset. `CUSTOM_CA_FILE=/path/ca.pem` in `.dev.env` makes `make deploy` and `make upgrade` put the CA in a Secret and set `customCA.secretName` for your release, so the pods trust it for outbound TLS. For the sandbox, `SANDBOX_CA_FILE=/path/ca.pem make sandbox up` installs the CA into the sandbox's system trust (apt switches to https for the image build) and points its curl, pip and git at it, so `install-dev.sh`'s downloads and the inner Docker daemon's registry pulls verify against it. Set it when the sandbox is created: `make sandbox down` first if it exists. The kind node's own containerd is not covered.

### One owner at a time

There is one dev cluster and one worktree owns it. `make deploy` and `make upgrade` claim it, `make teardown` releases it. A deploy from another worktree fails while it is owned: tear down from the owner, or rerun with `FORCE_OWNER=1` to take over. `make deploy-owner` shows who owns it.

### Development database passwords

The chart generates every database password and reuses it on each upgrade, so `.dev.env` holds none. Read them with `make show-db-passwords`, or one at a time:

```bash
kubectl get secret backend-db -n fn -o jsonpath='{.data.password}' | base64 -d
```

### Loading real sample data

Real experiments (UC1 and its seeded OMOP database) run from their own release in the `experiments` namespace. See [experiments/README.md](experiments/README.md).

## Deploy to production

Production is the same chart with different values: an external Postgres, Traefik and TLS on a real hostname, shared storage, and no development switches (`local_development`, `create_db_deployment`, Gitea, local images).

### 1. You need

- A Kubernetes cluster, with a node pool sized for the base pods plus the analytics task pods. The wiki's baseline is 4 vCPU / 8 GB per node, and Dagster adds to it. Tested on AKS, EKS, GKE and RKE2.
- `kubectl` and `helm` (v3) pointing at it, and `jq`.
- A PostgreSQL server the cluster can reach, with an admin login. The FN needs its own databases on it, not your research data. The chart creates them (see [Databases](#databases)).
- A hostname for the node, and a TLS certificate for it (or cert-manager).
- `ReadWriteMany` shared storage: Azure Files, AWS EFS, NFS, or a local path (single node only). Dagster task pods and the run pods write results to the same volume, so ReadWriteOnce disks do not work.
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

- **Do not copy values from `dev.values.yaml`.** `local_development`, `create_db_deployment`, `datasetDb`, `gitea`, the `localhost:5001` images and `fnDagster.sensors.minIntervalSeconds: 5` are for development only.
- **`fnDagster.db` is removed** and the chart fails if you set it. Dagster's database name and user come from `dagster.postgresql.postgresqlDatabase` and `postgresqlUsername`.
- **`namespaces` lives under `global`** (`global.namespaces.keycloak`, `.tasks`, `.quarantine`). A top-level `namespaces` fails the render.
- **Datasets** are not configured here. Register them through the API (`/global/datasets`). `datasetDb` is a development fixture and is rejected without `create: true`.
- Optional: `taskReview: true` makes tasks wait for approval before they run, and `smoketests: true` lets `helm test` create and delete real rows.

Every value, with comments, is in [k8s/federated-node/values.yaml](k8s/federated-node/values.yaml), and the chart's own README is [k8s/federated-node/README.md](k8s/federated-node/README.md).

#### Storage

Set exactly one backend under `storage`. The same volume class is used for task results and for Dagster's artifacts.

| Platform | Values | Also needs |
|---|---|---|
| Azure Files (AKS) | `on_aks: true`, `storage.azure.secretName`, `storage.azure.shareName` | The file share exists already, plus the storage secret |
| AWS EFS (EKS) | `on_eks: true`, `storage.aws.fileSystemId`, optional `accessPointId` | The EFS CSI driver |
| NFS | `storage.nfs.url`, `.path`, `.provisioner` | The export is writable by uid 1000: `chown 1000:1000` and `chmod 775` |
| Local path | `storage.local.path`, `.dbpath`, `.artifacts` | Single node only; the pods are pinned to the node that holds the data |

Set `storage.nfs.provisioner` (for example `nfs.csi.k8s.io`) even without that driver installed: the chart writes it into the artifacts StorageClass, which is invalid empty. The wiki's per-platform pages have the full walk-throughs for [Azure](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-Azure), [AWS](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-AWS), [GCP](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-GCP) and [on-premises](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Deploy-On-Premises) (MetalLB or NodePort for Traefik, an existing ingress controller, pod security labels). Take only their storage, ingress and TLS parts.

#### TLS

Either create the `tls` secret yourself (step 4), or let cert-manager renew it: `cert-manager.enabled: true` plus `certs.azure.*` or `certs.aws` for DNS-01. For another CA, run cert-manager yourself and point `tls.secretName` at the secret it produces.

#### Custom CA

For outbound TLS to a git host, identity provider or registry signed by a private CA, or behind a TLS-intercepting proxy, put the CA in a Secret and name it:

```bash
kubectl create secret generic corp-ca -n "$NAMESPACE" --from-file=ca.crt=corp-ca.pem
```

```yaml
customCA:
  secretName: corp-ca     # or customCA.pem: | the PEM, to have the chart render the Secret
```

The CA is added to the system CAs of the backend, the Dagster code server, every Dagster run pod and Keycloak, and certificates are always verified: there is no way to skip verification. The pods restart when the CA changes on `helm upgrade`. A Secret changed outside Helm needs `kubectl rollout restart` on the backend and code server deployments and the Keycloak StatefulSet, or a reloader controller. The chart cannot give the nodes' containerd the CA: if the container registry is behind a private CA, install it on each node. For a dev kind cluster, `CUSTOM_CA_FILE` does this when the cluster is created (`scripts/cluster.sh`). Details, and what is not covered, are in the [chart README](k8s/federated-node/README.md#custom-ca).

#### Databases

By default the chart manages the databases: three init jobs connect as `db.superuser` and create `backend`, `keycloak_db` and `dagster` with their own roles and generated passwords. Re-running them is harmless.

If a DBA owns the databases and you have no admin login, set `db.manageRolesAndDatabases: false`. The chart then needs no superuser, creates nothing, and each role's password becomes a secret you supply. Install once and it prints the exact SQL and `kubectl` commands for your names. A `db-check` hook verifies the roles before anything else installs.

For ArgoCD, `helm diff`, External Secrets or Vault, set `db.createPasswordSecrets: false` and let that tool own the password secrets. The chart reads them at runtime and never needs the value at render time. See the wiki's [Installing ArgoCD](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/wiki/Installing-ArgoCD).

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
# Passwords the chart generated (backend, keycloak, dagster roles)
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

The chart creates a `ClusterRole` for the backend (pods, PVs, PVCs, jobs, secrets: it creates storage and task pods per task), so the user running `helm install` must be allowed to create cluster roles. Task network isolation is not built yet ([ADR 0022](project/decisions/0022-task-isolation.md)).

## Upgrade, uninstall, reinstall

**Upgrade** with the same command as the install and a new `--version`. Passwords are reused, hook job names carry a hash so an image change does not fail on an immutable Job, and the backend applies database migrations itself (an init container runs `alembic upgrade head` before it starts).

```bash
helm repo update
helm upgrade --install federatednode federated-node/federated-node \
  --devel --version <NEW_VERSION> -f values.yaml -n federated-node --timeout 15m
```

Keycloak's platform credentials stay put across upgrades. To rotate them on purpose, raise `keycloak.credentialGeneration` by one, or set `keycloak.credentialRotation.enabled: true` for a monthly rotation.

**Uninstall** with `helm uninstall federatednode -n federated-node`. Helm does not remove what the hooks created: the generated password secrets (label `federatednode.com/generated-password=true`), the init jobs, the dataset credential secrets the backend wrote, and the data behind the Postgres volume if the chart ran the database.

**Reinstall onto the same external database server** works: the init jobs set each role's password to the newly generated one (`ALTER ROLE`), and the databases and their data are still there. Drop the databases first if you want a clean start.

**Reinstall with the chart's own Postgres** (`create_db_deployment: true`, development) is the exception. Postgres only reads its password when it first creates the data directory, so the data and the superuser secret go together: keep both or neither. If you delete only the secret, the install stops with a "stale postgres data" message that lists the two ways out.

For a throwaway development cluster, `make teardown` does all of this for you. Never run it against production: it deletes the namespaces and the data.

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
