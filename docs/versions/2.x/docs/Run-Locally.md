# Run Locally

This guide takes a Linux or WSL2 machine with nothing installed, and a fresh clone of the repository, to a running Federated Node 2.x on a local cluster. It stops when the node is up. Setting up a project and running a task are on the pages it links.

This is for trying and developing the FN. For a real cluster, use [Prerequisites](./Prerequisites) and [Deploy: Core](./Deploy-Core). The repo's [DEPLOYMENT.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/dagster-main/DEPLOYMENT.md#run-it-locally) is the source for this page, and the repo wins where they differ.


## What you end up with

- A local [kind](https://kind.sigs.k8s.io/) cluster with the FN installed: the backend, Dagster, Keycloak and Postgres. You can add a Gitea inside it as your git host.
- A local image registry and two pull-through caches, so rebuilds are quick.
- [Tilt](https://tilt.dev/), which port-forwards the services to localhost and reloads the code when you edit it.


## 1. Install the tools

| Tool | Why |
|---|---|
| `git`, `curl`, `jq` | clone, installers, scripts |
| Docker | builds the images, runs kind and the local registries. `docker ps` must work without `sudo` |
| `kubectl`, `helm` (v3), `kind` | the cluster and the chart |
| `tilt` | the port-forwards, and live reload |

On Debian, Ubuntu or WSL:

```sh
sudo apt update
sudo apt install -y git curl jq
```

Install the rest from their own guides: [Docker](https://docs.docker.com/engine/install/), [kubectl](https://kubernetes.io/docs/tasks/tools/), [helm](https://helm.sh/docs/intro/install/), [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installing-from-release-binaries) and [Tilt](https://docs.tilt.dev/install.html). Use Helm v3 and current releases of the others.

Check that everything is on the PATH:

```sh
for t in git curl jq docker kubectl helm kind tilt; do command -v $t >/dev/null || echo "missing: $t"; done
```


## 2. Clone

```sh
git clone https://github.com/Aridhia-Open-Source/PHEMS_federated_node.git
cd PHEMS_federated_node
git checkout dagster-main
```

Run every command from here on from the repo root, unless a step says otherwise.

One dev cluster has one owner at a time. `make deploy` and `make upgrade` claim it, and `make teardown` releases it. To deploy from a second copy of the repo, tear the first down, or rerun the deploy with `FORCE_OWNER=1`. `make deploy-owner` shows who owns it.


## 3. Local config

Two files, both gitignored. Do this before the cluster step.

```sh
cp .dev.env.example .dev.env
cp k8s/federated-node/dev.example.values.yml k8s/federated-node/dev.values.yaml
```

In `.dev.env`, set:

| Variable | Set it to |
|---|---|
| `KEYCLOAK_FIRST_USER_EMAIL` | your email. It is your admin login for the API |
| `KEYCLOAK_FIRST_USER_PASSWORD` | a password you will remember. Quote it if it has special characters, because bash reads the file |

Leave `CLUSTER_NAME=fn`, `NAMESPACE=fn`, `RELEASE_NAME=fn-dev` and `DOCKER_TAG=v1` as they are, and leave the other lines alone. `.dev.env` explains each one.

In `k8s/federated-node/dev.values.yaml`, leave `db.host` as `db.fn.svc`, which has to match `NAMESPACE`, and every image `tag` as `v1`, which has to match `DOCKER_TAG`. The chart generates the database passwords, so neither file holds one.

The example values do not run a Gitea. To have one in the cluster as your git host, add this to `dev.values.yaml`:

```yaml
gitea:
  enabled: true
```


## 4. Cluster and deploy

```sh
make helm_deps       # fetch the chart's subcharts (a fresh clone has none)
make cluster up      # a local registry, two pull-through caches, and a kind cluster called fn
make deploy          # build every image, install the chart (up to 10 minutes)
```

The first run is slow, because Docker has no cache yet. At the end `make deploy` prints the database passwords the chart generated. Read them again any time with `make show-db-passwords`. `make deploy` runs `helm install`, so to apply a chart change to the running node use `make upgrade`, and use `make teardown` first to start from empty data. A deploy also stops a running Tilt, so deploy first and start Tilt after.

Start Tilt in a second terminal and leave it running:

```sh
tilt up
```

Wait until its resources are green. Once the Dagster code location has loaded, the `dagster-reload` resource prints the list of URLs: that is your ready signal.

| What | Where |
|---|---|
| Backend API | http://localhost:5000 (docs at `/docs`) |
| Dagster UI | http://localhost:3000 |
| Gitea (if enabled) | http://localhost:4000 |
| Keycloak | http://localhost:8080 |
| Postgres | `localhost:5432` |
| Tilt dashboard | http://localhost:10350 |

Check that it is healthy:

```sh
kubectl config current-context        # kind-fn
kubectl get pods -n fn                # all Running
kubectl get jobs -A                   # the *-db-init and keycloak-realm-init jobs Completed
source .dev.env
curl -sS -X POST localhost:5000/login \
  -F "username=$KEYCLOAK_FIRST_USER_EMAIL" \
  -F "password=$KEYCLOAK_FIRST_USER_PASSWORD" | jq -r .token
```

The login prints a token when the backend and Keycloak work. Do not paste it anywhere.

Tilt watches the code and updates the running pods, so you do not redeploy for a change to `webserver/app/` or `dagster/app/`. `tilt trigger backend` rebuilds one service, `make tilt-down` stops Tilt and `make tilt-open` opens its dashboard.


## 5. Set up a project

A new node does nothing until a project is set up and the sensors are started.

1. Set up a project with the API, as in [Set up a project](./Set-Up-A-Project). Use `http://localhost:5000` as the node's address, and log in with the first user from `.dev.env`.
2. Start the Dagster sensors: every sensor starts stopped ([Operations](./Operations#start-the-sensors)). Start them again after each new `make deploy` or `make teardown`.
3. Ask for a task with a pull request: [Researcher guide](./Researcher-Guide).

If you use the cluster's Gitea, the backend and Dagster reach it inside the cluster, not through the Tilt port-forward. Give the git provider `http://gitea.fn.svc:4000` as its `uri` and `http://gitea.fn.svc:4000/api/v1` as its `api_uri` (`fn` is your `NAMESPACE`). You browse Gitea, and make tokens in it, at http://localhost:4000.


## Troubleshooting

| What you see | What to do |
|---|---|
| `Connection refused` on localhost 5000, 4000 or 3000 | Tilt must be running (`tilt up`) |
| Helm will not render, or the chart's subcharts are missing | `make helm_deps` |
| `make deploy`: `dev cluster is owned by ...` | Tear down from the owning copy, or `FORCE_OWNER=1 make deploy`. `make deploy-owner` shows the owner |
| `make deploy` fails on an existing release | `make deploy` only installs. Use `make upgrade` for a chart change. If the release is stuck, `make teardown` then `make deploy` |
| `stale postgres data` on reinstall | Postgres only reads its password when it first creates its data. Keep the password secret and the data, or delete both: `make teardown` does |
| Pods in `ImagePullBackOff`, or the chart fails on the database host | A stale or hand-edited `dev.values.yaml`. Compare it with `dev.example.values.yml` |
| A pod is stuck in `CrashLoopBackOff` | `kubectl describe pod <pod> -n fn` and `kubectl logs <pod> -n fn` |
| A merged pull request does nothing | The sensors are stopped by default: [Operations](./Operations#start-the-sensors) |


## Teardown and starting over

| Goal | Command |
|---|---|
| Remove the release and all its data, keep the cluster | `make teardown`, then `make deploy` again |
| Delete the cluster, keep the registries and their images | `make cluster down`, then `make cluster up` |
| Delete the cluster and the registries | `./scripts/cluster.sh down --remove-registries` |
| Teardown, new cluster and deploy in one go | `make nuke` |

`make teardown` wipes the node's data and releases the cluster's owner. After `make teardown` and `make deploy`, or `make nuke`, run `tilt up` again and start the sensors again. Your `.dev.env` and `dev.values.yaml` are untouched. Never run `make teardown` against a real node: it deletes the namespaces and the data.
