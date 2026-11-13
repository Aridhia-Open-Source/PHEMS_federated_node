# Run Locally

This guide takes a Linux or WSL2 machine with nothing installed, and a fresh clone of the repository, to a working Federated Node 2.x on a local cluster, and walks a pull request through it to a results pull request. You do it once against a Gitea that runs inside the cluster, and once against a GitHub repository and GitHub App of your own.

This is for trying and developing the FN. For a real cluster, use [Prerequisites](./Prerequisites) and [Deploy: Core](./Deploy-Core). The repo's [FRESH_SETUP.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/FRESH_SETUP.md) and [DEMO.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/DEMO.md) are the sources for this page, and the repo wins where they differ.


## What you end up with

- A local [kind](https://kind.sigs.k8s.io/) cluster with the FN installed, and a Gitea running inside it.
- A small demo database, registered with the node as a dataset.
- `fncli`, a command-line tool, on your PATH. `fncli apply` sets a node up from files, and `fncli demo` walks one pull request through it, one confirmed step at a time: it opens and merges a pull request, waits for the task to run, and merges the results pull request. `fncli delete` cleans up. [Using fncli](./Using-fncli) explains the files.


## 1. Install the tools

| Tool | Why |
|---|---|
| `git`, `make`, `curl`, `jq` | clone, the Makefile, installers, scripts |
| Docker | builds the images, runs kind and the local registries. `docker ps` must work without `sudo` |
| `kubectl`, `helm` (v3), `kind` | the cluster and the chart |
| `tilt` | the port-forwards fncli needs, and live reload |
| Python 3.12 or newer, and `pipx` | installs `fncli` |
| `gh` (optional) | gives fncli a GitHub token for the GitHub demo, if you do not set `RESEARCHER_GIT_TOKEN` |

On Debian, Ubuntu or WSL:

```sh
sudo apt update
sudo apt install -y git curl jq pipx
python3 --version        # must be 3.12 or newer
```

Then install the rest from their own guides: [Docker](https://docs.docker.com/engine/install/), [kubectl](https://kubernetes.io/docs/tasks/tools/), [helm](https://helm.sh/docs/intro/install/), [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installing-from-release-binaries) and [Tilt](https://docs.tilt.dev/install.html). The repo pins only Helm v3 and Python 3.12; use current releases of the others.

Check that everything is on the PATH:

```sh
for t in git mise curl jq docker kubectl helm kind tilt pipx; do command -v $t >/dev/null || echo "missing: $t"; done
```


## 2. Clone

```sh
git clone https://github.com/Aridhia-Open-Source/PHEMS_federated_node.git
cd PHEMS_federated_node
git checkout beta
```

Run every command from here on from the repo root, unless a step says otherwise.

One dev cluster has one owner at a time. To work in a second copy of the repo, tear the first down, or deploy with `FORCE_OWNER=1`. `mise run worktree --name <dir> --branch <branch>` makes a sibling copy with your local config files copied over.


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

Leave `CLUSTER_NAME=fn`, `NAMESPACE=fn` and `RELEASE_NAME=fn-dev` as they are, and leave the other lines alone. The cluster name and namespace are written into the Tiltfile, the example files and the port-forward scripts. Your own names go in your own files under `bootstrap/` (later steps), not here.

In `k8s/federated-node/dev.values.yaml`, set `nodeId` to a name for your node (any text; it is required, and names the node in the results it delivers). Leave `db.host` as `db.fn.svc`, which has to match `NAMESPACE`, and every image `tag` as `latest`. The Gitea block is already switched on, and the chart generates its admin password.


## 4. Install fncli

Do this before the deploy in step 5: `mise run deploy` runs `fncli experiment deploy`.

```sh
pipx ensurepath          # then open a new terminal
pipx install --force --editable './dagster[cli]'
fncli hello-world        # Hello, world!
```

The editable install points at the checkout it was run from. To use another checkout, run the same `pipx install` from there.

Make your **context file**. It says which node fncli works on, and which project and way `fncli trigger` uses when you do not say. It is gitignored, so it stays local:

```sh
cp bootstrap/examples/context.yaml bootstrap/context.yaml
```

The example already matches this guide: nexus-api at `http://localhost:5000`, the kubectl context `kind-fn`, the Keycloak namespace, and `.dev.env` as the env file. Set `defaults.project` to the demo you run: `demo-gitea` or `demo-github`.


## 5. Cluster and deploy

```sh
mise run helm-deps       # fetch the chart's subcharts (a fresh clone has none)
mise run cluster-up      # a local registry, two pull-through caches, and a kind cluster called fn
mise run deploy          # build every image, install the chart (up to 10 minutes)
```

The first run is slow, because Docker has no cache yet. At the end `mise run deploy` prints the database passwords the chart generated. It runs `helm install`, so a second run on a live release fails: use `make upgrade` for chart changes, or `mise run teardown` first. It also stops a running Tilt, so deploy first and start Tilt after.

Start Tilt in a second terminal and leave it running:

```sh
tilt up --stream
```

Wait until its resources are green. Once the Dagster code location has loaded, the `dagster-reload` resource prints the list of URLs: that is your ready signal.

| What | Where |
|---|---|
| nexus-api | http://localhost:5000 (docs at `/docs`) |
| Gitea | http://localhost:4000 |
| Dagster UI | http://localhost:3000 |
| Keycloak | http://localhost:8080 |
| nexus UI | http://localhost:8088/nexus-ui/ |
| Tilt dashboard | http://localhost:10350 |

Check that it is healthy:

```sh
kubectl config current-context        # kind-fn
kubectl get pods -n fn                # all Running, a gitea pod among them
kubectl get jobs -A                   # the *-db-init and keycloak-realm-init jobs Completed
source .dev.env
curl -sS -X POST localhost:5000/login \
  -F "username=$KEYCLOAK_FIRST_USER_EMAIL" \
  -F "password=$KEYCLOAK_FIRST_USER_PASSWORD" | jq -r .token
```

The login prints a token when nexus-api and Keycloak work. Do not paste it anywhere.


## 6. The demo database and the sensors

Both demos use one dataset, `demo-db`: a tiny Postgres with a `cdm.person` table of three rows and an empty `results` schema, in its own `experiments` release.

```sh
fncli experiment deploy                 # the release: the database, its role and secret
fncli experiment seed demo          # the schemas and rows
fncli experiment setup demo         # registers demo-db (and its secret) with the node
kubectl get pods -n experiments     # the database Running
```

Every Dagster sensor starts stopped, and nothing runs a merged pull request until you start them:

```sh
fncli start-sensor --group all
fncli sensor-status
```

If it says a sensor is not found, Dagster is still loading its code: wait a minute and run it again. After a new `mise run deploy` or `mise run teardown`, start the sensors again.


## 7. The Gitea demo

Everything lives in the cluster's Gitea, so nothing outside is needed. The demo is two files: the global resources (the git provider, the OAuth app secrets and the two repositories), and the project, which only assigns them and the dataset.

```sh
fncli diff  -f examples/globals-gitea.yaml          # preview: reads only
fncli apply -f examples/globals-gitea.yaml          # creates the provider, secrets and both Gitea repos
fncli apply -f examples/projects/demo-gitea.yaml    # the project and its assignments (uses demo-db)
fncli demo  -f examples/projects/demo-gitea.yaml    # the guided pull request walk
```

`apply` prints what it will change, asks, then does it. Run the diff again afterwards: it should show nothing left to change.

`fncli demo` creates and deletes nothing. It first checks that the node matches the project file, and stops with the rows that differ if it does not, so run the applies first. Before each step it says what the step does and shows the equivalent command. **Enter** runs it, **s** skips it, **q** quits. After each step it prints `Open:` addresses for your browser, and the objects it made. The pull request step waits up to 5 minutes for the task to run. Log in to the Gitea pages as `gitea_admin`. Useful options:

- `-y` runs every step without asking.
- `--from N` starts at step N, for example after a failed step.

Run the demo again as often as you like. `fncli demo -f examples/projects/demo-gitea.yaml examples/demo-failing.json` makes the task fail on purpose, to see the failure path. Without the guided checks, `fncli trigger --pr --merge --watch examples/demo.json` opens, merges and follows a pull request directly.

Clean up:

```sh
fncli delete -f examples/projects/demo-gitea.yaml           # the project only
fncli delete -f examples/globals-gitea.yaml --all           # also the shared repos, secrets and provider
```

Delete is a soft delete, and it skips anything another project still uses. The Gitea repos and OAuth apps stay in Gitea, and the next run reuses them. The dataset `demo-db` is not in these files, so neither delete touches it.


## 8. The GitHub demo with your own repository

fncli never creates or deletes GitHub repositories, tokens or Apps. You make them, and your files point at them.

1. **Create the repository** on GitHub, under an account or organisation you control. It must already have a commit on its default branch (tick "Add a README"). One repository plays both roles: the trigger and the results repository.
2. **Create a GitHub App** and install it on only that repository, as in [Set up a project](./Set-Up-A-Project#github): Contents and Pull requests with read and write, webhook off. Note the **App ID** and the **installation ID**, and generate a private key.
3. **Keep the key outside the repo**, for example:

   ```sh
   mkdir -p ~/.config/phems
   mv <where the browser saved it>/<app>.private-key.pem ~/.config/phems/<your-app>.private-key.pem
   chmod 600 ~/.config/phems/<your-app>.private-key.pem
   ```
4. **Add the two ids to `.dev.env`**, which is the env file your context names:

   ```sh
   GH_APP_ID=<your App ID>
   GH_INSTALLATION_ID=<your installation ID>
   ```
5. **Give fncli a researcher token.** The demo's pull requests into the trigger repository are your own work, not the node's, so they do not use the App. Either run `gh auth login`, or put `RESEARCHER_GIT_TOKEN=<token>` in `.dev.env`, a personal access token that can write to the repository.
6. **Copy the examples and edit the copies.** Your copies under `bootstrap/` are gitignored:

   ```sh
   mkdir -p bootstrap/projects
   cp bootstrap/examples/globals-github.yaml bootstrap/globals-<your-name>-github.yaml
   cp bootstrap/examples/projects/demo-github.yaml bootstrap/projects/<your-name>-github.yaml
   ```

   | Change | Where |
   |---|---|
   | The repository address | The globals file, for the trigger and the results repository, and the project file, for both: all four places, `https://github.com/<owner>/<repo>` |
   | The secret label | The globals file: the `secrets:` key, and `secret:` under both repositories. Lowercase letters, digits, `-` and `.` only |
   | The private key path | The globals file, `PRIVATE_KEY: {file: ...}`. `~` works |
   | `watch_dir` and `target_dir` | The project file. Directories in your repository, for example `mgmt/requests/` and `mgmt/results/`. They must not overlap, because the results pull requests go to the same repository and must not look like triggers |
   | `base_branch` | The project file, in both places: your repository's default branch |
   | The project name | The project file. Different from your Gitea project's |

   Leave the `providers:` block and the dataset `demo-db` as they are.
7. **Diff, apply, demo, delete:**

   ```sh
   fncli diff  -f bootstrap/globals-<your-name>-github.yaml
   fncli apply -f bootstrap/globals-<your-name>-github.yaml
   fncli apply -f bootstrap/projects/<your-name>-github.yaml
   fncli demo  -f bootstrap/projects/<your-name>-github.yaml
   fncli delete -f bootstrap/projects/<your-name>-github.yaml
   fncli delete -f bootstrap/globals-<your-name>-github.yaml --all
   ```

   In the diff, `GH_APP_ID`, `GH_INSTALLATION_ID` and the key file must say `set`. The demo asks nexus-api for a token for each repository and calls GitHub with it, then opens a pull request into your repository, merges it, and later merges the results pull request, which you can watch in your repository.

Nothing is deleted in your GitHub repository, and the dataset stays.


## Troubleshooting

| What you see | What to do |
|---|---|
| `... is for kubectl context kind-fn, but the current one is ...` | `kubectl config use-context kind-fn` |
| `context.yaml not found ...` | `cp bootstrap/examples/context.yaml bootstrap/context.yaml`, or give `--context FILE` |
| `node.env_file ... not found` | The env file must exist in or above the context file's directory. Make `.dev.env` (step 3) |
| `fncli: command not found` | `pipx ensurepath`, then a new terminal |
| `No such command 'diff'` or `No module named 'fncli'` | fncli points at another checkout: rerun the `pipx install` from this one |
| `Nothing was applied, these secret values cannot be read`, or `missing` in the diff | Set what it names: `GH_APP_ID` and `GH_INSTALLATION_ID` in `.dev.env`, the key file at the path in your globals file, and for the demo database the `fncli experiment` steps |
| `No experiments deployment: run fncli experiment deploy first` | `fncli experiment deploy` |
| `Writing to a GitHub repo needs RESEARCHER_GIT_TOKEN, or gh auth login` | Step 8, item 5 |
| A merged pull request does nothing | `fncli sensor-status`. Sensors are stopped by default: `fncli start-sensor --group all` |
| `fncli demo`: `The node does not match ... yet` | `fncli apply` the globals file, then the project file, then the demo again |
| A demo step failed | Fix the cause and rerun with `--from N` |
| `Connection refused` on localhost 5000, 4000 or 3000 | Tilt must be running (`tilt up --stream`) |
| Helm will not render, or the chart's subcharts are missing | `mise run helm-deps` |
| `mise run deploy`: `dev cluster is owned by ...` | Tear down from the owning copy, or `mise run deploy --force-owner`. `mise run deploy-owner` shows the owner |
| `mise run deploy` fails on an existing release | It runs `helm install`. Use `make upgrade`, or `mise run teardown` then `mise run deploy` |
| `stale postgres data` on reinstall | Postgres only reads its password when it first creates its data. Keep the password secret and the data, or delete both: `mise run teardown` does |
| `delete --all` ends with `Skipped, the backend refused` | A project outside the file still uses what it deletes (the other demo's repository, say). Delete that project first |
| Pods in `ImagePullBackOff`, or the chart fails on `nodeId` or the database host | A stale or hand-edited `dev.values.yaml`. Compare it with `dev.example.values.yml` |
| A pod is stuck in `CrashLoopBackOff` | `kubectl describe pod <pod> -n fn` and `kubectl logs <pod> -n fn` |


## Teardown and starting over

| Goal | Command |
|---|---|
| Remove a demo project from the node | `fncli delete -f` its project file, then `fncli delete -f` its globals file with `--all` |
| Remove the release and all its data, keep the cluster | `mise run teardown`, then `mise run deploy` again |
| Delete the cluster, keep the registries and their images | `mise run cluster-down`, then `mise run cluster-up` |
| Delete the cluster and the registries | `mise run cluster-down --remove-registries` |
| Teardown, new cluster and deploy in one go | `mise run teardown`, `mise run cluster-down`, `mise run cluster-up`, then `mise run deploy` |

`mise run teardown` wipes the node's data and releases the cluster's owner. It keeps the `experiments` release, so the demo database survives. After `mise run teardown` and `mise run deploy`, or after a new cluster, run `tilt up --stream` again, then `fncli start-sensor --group all`, then the demo. Your `.dev.env`, `dev.values.yaml`, `bootstrap/context.yaml`, your files under `bootstrap/` and the App's key file are untouched. After `make nuke`, run `fncli experiment deploy` again if `kubectl get pods -n experiments` shows nothing.

`fncli experiment down` removes every experiment's dataset from the node and then the release. It stops while a demo project still uses `demo-db`: delete that project first.
