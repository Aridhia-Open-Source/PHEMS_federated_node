# Run Locally

This guide takes a Linux or WSL2 machine with nothing installed, and a fresh clone of the repository, to a working Federated Node 2.x on a local cluster, and walks a pull request through it to a results pull request. You do it once against a Gitea that runs inside the cluster, and once against a GitHub repository and GitHub App of your own.

This is for trying and developing the FN. For a real cluster, use [Prerequisites](./Prerequisites) and [Deploy: Core](./Deploy-Core). The repo's [FRESH_SETUP.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/FRESH_SETUP.md) and [DEMO.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/DEMO.md) are the sources for this page, and the repo wins where they differ.


## What you end up with

- A local [kind](https://kind.sigs.k8s.io/) cluster with the FN installed, and a Gitea running inside it.
- A small demo database, registered with the node as a dataset (a Kubernetes resource that the nexus operator syncs).
- `fncli`, a command-line tool, on your PATH. `kubectl apply` of the files in `config/` sets a node up, and `fncli demo` walks one pull request through it, one confirmed step at a time: it opens and merges a pull request, waits for the task to run, and merges the results pull request. `kubectl delete` cleans up. [Using fncli](./Using-fncli) explains the files.


## 1. Install the tools

| Tool | Why |
|---|---|
| `git`, `curl`, `jq` | clone, installers, scripts |
| Docker | builds the images, runs kind and the local registries. `docker ps` must work without `sudo` |
| `kubectl`, `helm` (v3), `kind` | the cluster and the chart |
| `tilt` | the port-forwards fncli needs, and live reload |
| [mise](https://mise.jdx.dev/) | `mise run setup` installs Python 3.12 and `fncli` (step 4); it also runs the repo's `mise run` tasks |
| `gh` (optional) | gives fncli a GitHub token for the GitHub demo, if you do not set `RESEARCHER_GIT_TOKEN` |

On Debian, Ubuntu or WSL:

```sh
sudo apt update
sudo apt install -y git curl jq
```

Then mise, from its [installer](https://mise.jdx.dev/getting-started.html). Activate it in your shell, and open a new terminal:

```sh
curl https://mise.run | sh
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc     # zsh: ~/.zshrc and `mise activate zsh`
```

Install the rest from their own guides: [Docker](https://docs.docker.com/engine/install/), [kubectl](https://kubernetes.io/docs/tasks/tools/), [helm](https://helm.sh/docs/intro/install/), [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installing-from-release-binaries) and [Tilt](https://docs.tilt.dev/install.html). The repo pins only Helm v3 and Python 3.12; use current releases of the others.

Check that everything is on the PATH:

```sh
for t in git curl jq docker kubectl helm kind tilt mise; do command -v $t >/dev/null || echo "missing: $t"; done
```


## 2. Clone

```sh
git clone https://github.com/Aridhia-Open-Source/PHEMS_federated_node.git
cd PHEMS_federated_node
git checkout beta
```

Run every command from here on from the repo root, unless a step says otherwise.

One dev cluster has one owner at a time. To work in a second copy of the repo, tear the first down, or deploy with `--force-owner`. `mise run worktree --name <dir> --branch <branch>` makes a sibling copy with your local config files copied over.


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

Leave `CLUSTER_NAME=fn`, `NAMESPACE=fn` and `RELEASE_NAME=fn-dev` as they are, and leave the other lines alone. The cluster name and namespace are written into the Tiltfile, the example files and the port-forward scripts. Your own names go in your own copies of the files in `config/` (later steps), not here.

In `k8s/federated-node/dev.values.yaml`, set `nodeId` to a name for your node (any text; it is required, and names the node in the results it delivers). Leave `db.host` as `db.fn.svc`, which has to match `NAMESPACE`, and every image `tag` as `latest`. The Gitea block is already switched on, and the chart generates its admin password.


## 4. Install fncli

Do this before the deploy in step 5: `mise run deploy` runs `fncli experiment deploy`.

```sh
mise trust               # if mise asks
mise run setup
fncli hello-world        # Hello, world!
```

`mise run setup` installs fncli, editable, into `.venv` at the repo root. With mise activated, `fncli` is on your PATH anywhere in the repo. The install belongs to that checkout, so a worktree needs its own `mise run setup`. If you installed fncli with pipx before, remove that copy: `pipx uninstall phems`.

Make your **context file**. It says which node fncli works on, and which project and way `fncli trigger` uses when you do not say. It is gitignored, so it stays local:

```sh
cp bootstrap/examples/context.yaml bootstrap/context.yaml
```

The example already matches this guide: nexus-api at `http://localhost:5000`, the kubectl context `kind-fn`, the Keycloak namespace, and `.dev.env` as the env file. Set `defaults.project` to the demo you run: `demo-gitea` or `demo-github`.


## 5. Cluster and deploy

```sh
mise run helm deps       # fetch the chart's subcharts (a fresh clone has none)
mise run cluster up      # a local registry, two pull-through caches, and a kind cluster called fn
mise run deploy          # build every image, install the chart (up to 10 minutes)
```

The first run is slow, because Docker has no cache yet. At the end `mise run deploy` prints the database passwords the chart generated. It runs `helm upgrade --install`, so it is safe to rerun for chart changes; use `mise run teardown` first to start from empty data. It also stops a running Tilt, so deploy first and start Tilt after.

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
fncli experiment setup demo         # waits for demo-db (and its secret) to sync to the node
kubectl get pods -n experiments     # the database Running
```

Every Dagster sensor starts stopped, and nothing runs a merged pull request until you start them:

```sh
fncli start-sensor --group all
fncli sensor-status
```

If it says a sensor is not found, Dagster is still loading its code: wait a minute and run it again. After a new `mise run deploy` or `mise run teardown`, start the sensors again.


## 7. The Gitea demo

Everything lives in the cluster's Gitea, so nothing outside is needed. The demo is two files in `config/`: `gitea.yaml` (the git provider) and `demo.yaml` (the OAuth app secrets, the two repositories and the project, which assigns the dataset).

```sh
fncli gitea setup -f config/gitea.yaml -f config/demo.yaml    # the Gitea repositories, and a Kubernetes Secret with each one's OAuth app
kubectl apply -f config/                 # the provider, NodeSecrets, repositories and the project (uses demo-db)
kubectl get fn -n fn                     # each resource's Synced and Message: wait for them all to sync
fncli demo --project demo-gitea          # the guided pull request walk
```

`fncli gitea setup` keeps a Secret that exists, so it is safe to rerun. The nexus operator syncs the applied resources to nexus-api, and says in `Message` what a resource is waiting for.

`fncli demo` creates and deletes nothing. It first reads the project's Project resource, and stops, showing the operator's message, if it is not synced, so apply first. Before each step it says what the step does and shows the equivalent command. **Enter** runs it, **s** skips it, **q** quits. After each step it prints `Open:` addresses for your browser, and the objects it made. The pull request step waits up to 5 minutes for the task to run. Log in to the Gitea pages as `gitea_admin`. Useful options:

- `-y` runs every step without asking.
- `--from N` starts at step N, for example after a failed step.

Run the demo again as often as you like. `fncli demo --project demo-gitea triggers/examples/demo-failing.json` makes the task fail on purpose, to see the failure path. Without the guided checks, `fncli trigger --pr --merge --watch triggers/examples/demo.json` opens, merges and follows a pull request directly.

Clean up:

```sh
kubectl delete -f config/demo.yaml       # the project, repositories and NodeSecrets (config/gitea.yaml stays)
```

The operator soft-deletes the records, and keeps anything another project still uses. The Gitea repos, OAuth apps and Secrets stay, and the next run reuses them. The dataset `demo-db` is the experiments chart's, so the delete does not touch it.


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
6. **Copy the example and edit the copy.** The file is `config/github/demo-github.yaml`:

   ```sh
   cp config/github/demo-github.yaml config/github/<your-name>-github.yaml
   ```

   | Change | Where |
   |---|---|
   | The repository address | Both Repositories' `spec.uri`, and the project's `repository:` under `triggers` and `results`: all four places, `https://github.com/<owner>/<repo>` |
   | The NodeSecret name | The NodeSecret's `metadata.name`, and `spec.secret` of both Repositories. Lowercase letters, digits, `-` and `.` only |
   | The Kubernetes Secret name | The NodeSecret's `spec.fromSecret.name`, and the `kubectl create secret` below |
   | `watchDir` and `targetDir` | The project. Directories in your repository, for example `mgmt/requests/` and `mgmt/results/`. They must not overlap, because the results pull requests go to the same repository and must not look like triggers |
   | `baseBranch` | The project, in both places: your repository's default branch |
   | The project name | The project. Different from your Gitea project's |

   Leave the GitProvider and the dataset `demo-db` as they are.
7. **Store the App's values, apply, demo, delete:**

   ```sh
   kubectl create secret generic phems-sandbox-github-app -n fn \
     --from-literal=APP_ID="$GH_APP_ID" --from-literal=INSTALLATION_ID="$GH_INSTALLATION_ID" \
     --from-file=PRIVATE_KEY=$HOME/.config/phems/<your-app>.private-key.pem
   kubectl apply -f config/github/<your-name>-github.yaml
   kubectl get fn -n fn                     # wait for every resource to sync
   fncli demo --project <your-project>
   kubectl delete -f config/github/<your-name>-github.yaml
   ```

   `GH_APP_ID` and `GH_INSTALLATION_ID` must be set in your shell (`set -a; source .dev.env; set +a`). The demo asks nexus-api for a token for each repository and calls GitHub with it, then opens a pull request into your repository, merges it, and later merges the results pull request, which you can watch in your repository.

Nothing is deleted in your GitHub repository, and the dataset stays.


## Troubleshooting

| What you see | What to do |
|---|---|
| `... is for kubectl context kind-fn, but the current one is ...` | `kubectl config use-context kind-fn` |
| `context.yaml not found ...` | `cp bootstrap/examples/context.yaml bootstrap/context.yaml`, or give `--context FILE` |
| `node.env_file ... not found` | The env file must exist in or above the context file's directory. Make `.dev.env` (step 3) |
| `fncli: command not found` | Activate mise in your shell (step 1), then open a new terminal. Or run `mise run setup` if you have not |
| `No such command 'gitea'` or `No module named 'fncli'` | Run `mise run setup` in this checkout. An old pipx copy: `pipx uninstall phems` |
| A resource in `kubectl get fn -n fn` is not synced | Read its `Message`: a Kubernetes Secret that is missing (`fncli gitea setup`, or `kubectl create secret` for GitHub), a dataset that is not on the node (the `fncli experiment` steps), or a repository not applied yet |
| `No experiments deployment: run fncli experiment deploy first` | `fncli experiment deploy` |
| `Writing to a GitHub repo needs RESEARCHER_GIT_TOKEN, or gh auth login` | Step 8, item 5 |
| A merged pull request does nothing | `fncli sensor-status`. Sensors are stopped by default: `fncli start-sensor --group all` |
| `fncli demo`: `Project ... is not synced to the node yet` | `kubectl get fn -n fn`, fix what the `Message` names, `kubectl apply -f config/` again, then the demo |
| A demo step failed | Fix the cause and rerun with `--from N` |
| `Connection refused` on localhost 5000, 4000 or 3000 | Tilt must be running (`tilt up --stream`) |
| Helm will not render, or the chart's subcharts are missing | `mise run helm deps` |
| `mise run deploy`: `dev cluster is owned by ...` | Tear down from the owning copy, or `mise run deploy --force-owner`. `mise run deploy-owner` shows the owner |
| `mise run deploy` fails on an existing release | It runs `helm upgrade --install`, so rerunning is safe. If the release is stuck, `mise run teardown` then `mise run deploy` |
| `stale postgres data` on reinstall | Postgres only reads its password when it first creates its data. Keep the password secret and the data, or delete both: `mise run teardown` does |
| A resource stays `Terminating` after `kubectl delete` | A project outside the file still uses it (the other demo's repository, say). Delete that project first |
| Pods in `ImagePullBackOff`, or the chart fails on `nodeId` or the database host | A stale or hand-edited `dev.values.yaml`. Compare it with `dev.example.values.yml` |
| A pod is stuck in `CrashLoopBackOff` | `kubectl describe pod <pod> -n fn` and `kubectl logs <pod> -n fn` |


## Teardown and starting over

| Goal | Command |
|---|---|
| Remove a demo project from the node | `kubectl delete -f` its file in `config/` |
| Remove the release and all its data, keep the cluster | `mise run teardown`, then `mise run deploy` again |
| Delete the cluster, keep the registries and their images | `mise run cluster down`, then `mise run cluster up` |
| Delete the cluster and the registries | `./scripts/cluster.sh down --remove-registries` |
| Teardown, new cluster and deploy in one go | `mise run teardown && mise run cluster down && mise run cluster up && mise run deploy` |

`mise run teardown` wipes the node's data and releases the cluster's owner. It keeps the `experiments` release, so the demo database survives. After `mise run teardown` and `mise run deploy`, or the full reset above, run `tilt up --stream` again, then `fncli start-sensor --group all`, then the demo. Your `.dev.env`, `dev.values.yaml`, `bootstrap/context.yaml`, your files under `config/` and the App's key file are untouched. The node resources and Secrets in namespace `fn` go with the namespace: run the `fncli gitea setup` and `kubectl apply` of the demo again. After the full reset, run `fncli experiment deploy` again if `kubectl get pods -n experiments` shows nothing.

`fncli experiment down` deletes every experiment's node project and uninstalls the release, which removes the datasets' resources. `demo-db` stays `Terminating` while a demo project still uses it: delete that project first (`kubectl delete -f config/demo.yaml`).
