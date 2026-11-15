# Fresh setup: from an empty machine to the Gitea and GitHub demos

This guide takes a Linux or WSL2 machine with nothing installed, and a fresh clone, to a working `fncli demo` against both Gitea and GitHub. You use your own GitHub repo, your own GitHub App and your own names.

The source of truth is the repo: [DEPLOYMENT.md](DEPLOYMENT.md), [MANAGEMENT.md](MANAGEMENT.md), [SETUP_GIT_APPS.md](SETUP_GIT_APPS.md), [dagster/fncli/README.md](dagster/fncli/README.md) and [experiments/README.md](experiments/README.md). Where this guide could not be confirmed from the code, it says `TODO(verify)`.

- [1. What you end up with](#1-what-you-end-up-with)
- [2. Install the tools](#2-install-the-tools)
- [3. Clone](#3-clone)
- [4. Local config](#4-local-config)
- [5. Install fncli](#5-install-fncli)
- [6. Cluster and deploy](#6-cluster-and-deploy)
- [7. The demo database and the sensors](#7-the-demo-database-and-the-sensors)
- [8. The Gitea demo](#8-the-gitea-demo)
- [9. The GitHub demo with your own repo](#9-the-github-demo-with-your-own-repo)
- [10. Troubleshooting](#10-troubleshooting)
- [11. Teardown and starting over](#11-teardown-and-starting-over)

## 1. What you end up with

A local Federated Node on a kind cluster, with Gitea running inside it, a small demo database, and `fncli` on your PATH. `kubectl apply` of the node resources in `config/` sets up one project: the git provider, the secrets, the repositories and the project (the nexus operator syncs them to nexus-api, ADR 0032). `fncli demo` then walks a pull request through it, one confirmed step at a time: it opens and merges a pull request, waits for the task to run, and merges the results pull request. `kubectl delete` cleans up. You run it twice: once on the in-cluster Gitea, and once on a GitHub repo of yours, with a GitHub App that you created.

## 2. Install the tools

You need these. The repo pins only two versions: Helm v3 and Python 3.12 or newer. It pins none for the rest, so use current releases.

| Tool | Why |
|---|---|
| `git`, `curl`, `jq` | clone, installers, scripts |
| Docker | builds the images, runs kind and the local registries |
| `kubectl`, `helm` (v3), `kind` | the cluster and the chart |
| `tilt` | the port-forwards fncli needs (nexus-api 5000, Gitea 4000, Dagster 3000), and live reload |
| [mise](https://mise.jdx.dev/) | `mise run setup` installs Python 3.12 and `fncli` (step 5); it also runs the repo's `mise run` tasks |
| `gh` (optional) | gives fncli a GitHub token for the GitHub demo, if you do not set `RESEARCHER_GIT_TOKEN` |

1. Base packages (Debian, Ubuntu, WSL):

   ```bash
   sudo apt update
   sudo apt install -y git curl jq
   ```

   mise, from its [installer](https://mise.jdx.dev/getting-started.html). Activate it in your shell, then open a new terminal:

   ```bash
   curl https://mise.run | sh
   echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc     # zsh: ~/.zshrc and `mise activate zsh`
   ```

2. Docker. The command below is Docker's own installer, not from this repo. Any Docker works as long as `docker ps` runs without `sudo`.

   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker "$USER"      # then open a new terminal
   docker ps
   ```

3. `kubectl` and `helm`, as in [.kind/README.md](.kind/README.md):

   ```bash
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   chmod +x kubectl
   sudo mv kubectl /usr/local/bin/

   curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   ```

4. `kind`, from the [kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/#installing-from-release-binaries). The repo has no install command for it.

   ```bash
   # x86_64 shown; the quick start has the arm64 line
   curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.30.0/kind-linux-amd64
   chmod +x ./kind
   sudo mv ./kind /usr/local/bin/kind
   ```

   > TODO(verify): the repo pins no kind version. `v0.30.0` is a guess at a release that works; the author's machine runs kind 0.31 (alpha), kubectl 1.33, helm 3.19, tilt 0.37 and Docker 28. That is for reference only, not a requirement.

5. Tilt, as in [.tilt/TILT.md](.tilt/TILT.md):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash
   tilt version
   ```

6. `gh` (optional). Follow [GitHub CLI for Linux](https://github.com/cli/cli/blob/trunk/docs/install_linux.md), or on Ubuntu try `sudo apt install gh`.

   > TODO(verify): the repo has no install command for `gh`, and the apt package may be old. Any `gh` that supports `gh auth token` is enough.

7. Check that everything is on the PATH:

   ```bash
   for t in git curl jq docker kubectl helm kind tilt mise; do command -v $t >/dev/null || echo "missing: $t"; done
   ```

## 3. Clone

```bash
git clone https://github.com/Aridhia-Open-Source/PHEMS_federated_node.git
cd PHEMS_federated_node
git checkout fncli-declarative-config
```

> TODO(verify): `fncli demo`, the demo resources in `config/` and the demo database exist only on the `fncli-declarative-config` branch at the time of writing. Once it is merged, stay on the default branch instead.

Run every command from here on from the repo root, unless a step says otherwise.

Worktrees are optional. One dev cluster has one owner at a time, so a second worktree needs the first one torn down, or `mise run deploy --force-owner`. To make a sibling worktree with your gitignored config copied over (`.dev.env`, `dev.values.yaml`, your context file under `bootstrap/` and your files under `triggers/`):

```bash
mise run worktree --name wt-mine --branch my-branch [--base <ref>]
cd ../wt-mine
```

Then run `mise run setup` in it (step 5) and run `mise run helm deps && mise run deploy`.

## 4. Local config

Two files, both gitignored. Do this before step 6: `scripts/cluster.sh` and `scripts/deploy.sh` read `.dev.env`.

1. Copy them.

   ```bash
   cp .dev.env.example .dev.env
   cp k8s/federated-node/dev.example.values.yml k8s/federated-node/dev.values.yaml
   ```

2. Edit `.dev.env`.

   | Variable | Set it to | Why |
   |---|---|---|
   | `KEYCLOAK_FIRST_USER_EMAIL` | `admin@fn.local` (the default), or your email | Your admin login for the API. `deploy.sh` stores it in the `keycloak-first-user` secret |
   | `KEYCLOAK_FIRST_USER_PASSWORD` | `admin` (the default), or a password you will remember | Same. Quote it if it has special characters, because the file is `source`d by bash |


   Leave `CLUSTER_NAME=fn`, `NAMESPACE=fn` and `RELEASE_NAME=fn-dev` as they are. They are written into more than this file: the Tiltfile allows only `kind-fn`, the context file names `kind-fn` and the files in `config/` name `gitea.fn.svc`, fncli translates only hosts ending in `fn.svc`, `scripts/portfwd.sh` uses `-n fn`, and the values file names `db.fn.svc`. Your own names go in your own copies of the files in `config/` (steps 8 and 9), not here.

   That is all `.dev.env` holds: deploy settings, the first Keycloak user and the optional GitHub ids. The node's address, kubectl context, Keycloak namespace and Gitea admin user are in `bootstrap/context.yaml`, and a project's repositories and dataset are node resources in `config/`.

   You add `GH_APP_ID`, `GH_INSTALLATION_ID` and optionally `RESEARCHER_GIT_TOKEN` in step 9.

3. Edit `k8s/federated-node/dev.values.yaml`.

   - `nodeId`: your own node name (any text). It is required, and names the node in the results it delivers.
   - `db.host` stays `db.fn.svc`, which must match `NAMESPACE`. Every image `tag` stays `latest`.
   - Gitea: the example's `gitea:` block already turns it on. The chart generates the admin password into the `gitea-admin` secret, so no password goes in the file.

No CA files or `cadir` are needed: nothing in the repo's scripts, Tiltfile or chart reads them.

## 5. Install fncli

Do this before the deploy in step 6: `mise run deploy` runs `fncli experiment deploy`.

```bash
mise trust               # if mise asks
mise run setup
fncli hello-world        # Hello, world!
```

`mise run setup` installs fncli, editable, into `.venv` at the repo root; with mise activated, `fncli` is on your PATH anywhere in the repo. The install belongs to that checkout, so a worktree needs its own `mise run setup`. If you installed fncli with pipx before, remove that copy: `pipx uninstall phems`.

fncli finds `.dev.env` by searching up from the current directory, so run it from inside the repo. It reads cluster secrets from the current kubectl context, which must be `kind-fn`.

Make your context file. It says which node fncli works on, and which project and way `fncli trigger` uses when you do not say. Every command that talks to the node reads it; fncli finds `bootstrap/context.yaml` from the current directory up. It is gitignored, so it stays local.

```bash
cp bootstrap/examples/context.yaml bootstrap/context.yaml
```

The example matches this guide: `url: http://localhost:5000`, `kube_context: kind-fn`, `keycloak_namespace: keycloak`, `env_file: .dev.env`. Change `defaults.project` to the name of your project when you have one (steps 8 and 9). `FNCLI_DEFAULT_PROJECT` and `FNCLI_DEFAULT_TRIGGER_TYPE` in the shell win over `defaults:`, and a flag wins over both. A command that uses a default says so on its first line.

## 6. Cluster and deploy

1. Fetch the chart's subcharts. `charts/` is gitignored, so a fresh clone has none and Helm will not render.

   ```bash
   mise run helm deps
   ```

2. Create the cluster and the registries.

   ```bash
   mise run cluster up
   ```

   It starts a registry at `localhost:5001` (your images) and two pull-through mirrors (`localhost:5002` Docker Hub, `localhost:5003` GHCR), then a kind cluster `fn` with the kubectl context `kind-fn`. Local volumes live in `~/.fn/data` (`FN_DATA_DIR`, fixed when the cluster is created).

3. Build the images and install the chart.

   ```bash
   mise run deploy
   ```

   It claims the dev cluster, renders the chart as a check, builds and pushes every image to `localhost:5001` (including `demo-fn`, the demo's task image, so there is no separate build step; they are `docker buildx bake` targets in `docker-bake.hcl`), creates the namespace and the `keycloak-first-user` secret, then runs `helm install` (up to 10 minutes). The first run is slow because Docker has no cache yet. At the end it prints the database passwords the chart generated.

   `mise run deploy` runs `helm upgrade --install`, so it is safe to rerun for chart changes; use `mise run teardown` first (step 11) to start from empty data. It also stops a running Tilt, so deploy first and start Tilt after.

4. Start Tilt in a second terminal and leave it running.

   ```bash
   tilt up --stream
   ```

   Wait until the resources are green. The `dagster-reload` resource prints the list of URLs once the Dagster code location has loaded: that is your ready signal.

   | What | Where |
   |---|---|
   | nexus-api | http://localhost:5000 (docs at `/docs`) |
   | Gitea | http://localhost:4000 |
   | Dagster UI | http://localhost:3000 |
   | Keycloak | http://localhost:8080 |
   | nexus UI | http://localhost:8088/nexus-ui/ |
   | Tilt dashboard | http://localhost:10350 |

   `mise run portfwd` also forwards some of these, but not Gitea, so use Tilt.

5. Check that it is healthy.

   ```bash
   kubectl config current-context        # kind-fn
   kubectl get pods -n fn                # all Running, a gitea pod among them
   kubectl get pods -n keycloak
   kubectl get jobs -A                   # the *-db-init and keycloak-realm-init jobs Completed
   curl -fsS localhost:4000 -o /dev/null && echo gitea up
   source .dev.env
   curl -sS -X POST localhost:5000/login \
     -F "username=$KEYCLOAK_FIRST_USER_EMAIL" \
     -F "password=$KEYCLOAK_FIRST_USER_PASSWORD" | jq -r .token
   curl -s localhost:5001/v2/_catalog    # lists demo-fn, nexus-api-fn, dagster-fn, ...
   ```

   The login prints a token when nexus-api and Keycloak work. Do not paste it anywhere.

## 7. The demo database and the sensors

Both demos use one dataset, `demo-db`. It is a tiny Postgres in its own `experiments` release and namespace. These are `fncli` commands, so step 5 comes first.

```bash
fncli experiment deploy
fncli experiment seed demo
fncli experiment setup demo
```

- `up` installs the `experiments` release: a Postgres with a database, a role and a generated password secret for each experiment under `experiments/`. Safe to rerun.
- `seed demo` loads `cdm.person` (three rows) and an empty `results` schema into `demo-db`, as `demo_user`. Safe to rerun.
- `deploy` also renders the dataset `demo-db` and its secret as node resources (namespace `experiments`), which the operator syncs to the node. `setup demo` waits for them to sync (it needs your context file from step 5). The demo project only assigns the dataset, so run this before it.
- Check: `kubectl get pods -n experiments` shows the database `Running`.

Start the Dagster sensors. Every sensor starts stopped, and `fncli demo` does not start them. Without them a merged pull request is never picked up.

```bash
fncli start-sensor --group all
fncli sensor-status
```

After a new `mise run deploy` or `mise run teardown`, start them again.

## 8. The Gitea demo

The demo is `config/demo.yaml`: two NodeSecrets (each one's Kubernetes Secret holds a Gitea OAuth app's credentials), the two repositories and the project `demo-gitea`, which assigns the dataset from step 7. The git provider is `config/gitea.yaml`, which `kubectl apply -f config/` applies with it. The format and the operator are in [ADR 0032](project/decisions/0032-declarative-node-config-through-an-operator.md).

1. Optional: use your own names. Copy `config/demo.yaml` to a file of your own in `config/` and edit the copy. Names may use only lowercase letters, digits, `-` and `.`.

   | Change | Where | Rule |
   |---|---|---|
   | NodeSecret names `demo-trigger-repo-creds` and `demo-results-repo-creds` | each NodeSecret's `metadata.name` and `spec.fromSecret.name`, and `spec.secret` of its Repository | Gitea tells OAuth apps apart by name, and fncli names each app after its NodeSecret. So they must differ from each other, from `fn-trigger-repo-creds` and `fn-results-repo-creds` (the e2e project's), and from the stock demo's if you also run it |
   | Repo names `demo-trigger-repo` and `demo-results-repo` | each Repository's `metadata.name` and `spec.uri`, and `repository:` in the project's `triggers` and `results` | Keep the host `gitea.fn.svc:4000` and the owner `gitea_admin`. `fncli gitea setup` creates the repos |
   | Project name `demo-gitea` | the Project's `metadata.name` | Yours, and different from your GitHub project's. Put it in `defaults.project` of your context file too |
   | `watchDir`, `targetDir`, `baseBranch` | the project's `triggers` and `results` | Optional. Keep `main`. The two directories must not overlap |

   Leave the dataset `demo-db` in the project's `datasets:`. It is the name of the database on the host, which the experiments chart creates, so renaming it makes the dataset unreachable.

2. Make the Gitea repos and the Secrets the NodeSecrets read. This creates the Gitea repositories of the file's Repository resources and, for each NodeSecret they name, a Gitea OAuth app named after it, and writes `CLIENT_ID`, `CLIENT_SECRET` and `REFRESH_TOKEN` into that NodeSecret's Kubernetes Secret. It keeps a Secret that exists, unless you pass `--rotate NODESECRET`. Run it before the apply below.

   ```bash
   fncli gitea setup -f config/demo.yaml
   ```

3. Apply the node resources, then check that the operator synced them.

   ```bash
   kubectl apply -f config/
   kubectl get fn -n fn
   ```

   Every row should show `Synced` true. A row that does not has its reason in `Message`: a missing Secret, a dataset that is not on the node, a repository the project names that is not applied yet. Fix it and apply again.

4. Run the guided demo. The trigger file is the JSON the pull request adds: `triggers/examples/demo.json` by default, `triggers/examples/demo-failing.json` for a task that fails. A path, or one relative to `triggers/`, works.

   ```bash
   fncli demo --project demo-gitea
   fncli demo --project demo-gitea triggers/examples/demo-failing.json
   ```

   Without `--project` it uses `defaults.project` of your context file. The demo creates and deletes nothing. It reads the project's Project resource and stops, showing the operator's message, unless the project is synced: apply first. Before each step it says what the step does and shows the equivalent command. Enter runs it, `s` skips it, `q` quits. After each step it prints `Open:` addresses for the browser and the objects that were made. The pull request step waits up to 5 minutes for the task to run. Useful options:

   - `-y` runs every step without asking.
   - `--from N` starts at step N, for example after a failed step.

   You can run the demo again as often as you like. The pull request step is `fncli trigger`, which you can also run alone: `fncli trigger triggers/examples/demo.json --merge --watch` triggers `defaults.project` of your context file by pull request, and says which defaults it used on its first line.

   For the Gitea web pages that the `Open:` lines point to, log in as `gitea_admin`.

   > TODO(verify): the password is the chart-generated `gitea-admin` secret, and `mise run show-db-passwords` should list it. Not confirmed on a fresh install.

5. Clean up.

   ```bash
   kubectl delete -f config/demo.yaml      # the project, repositories and NodeSecrets (config/gitea.yaml stays)
   ```

   - The operator deletes them from the node too. It skips what another project still uses, and says so in `kubectl get fn -n fn`.
   - The Gitea repos, OAuth apps and Kubernetes Secrets stay, and the next run reuses them.
   - The dataset `demo-db` is the experiments chart's, so the delete does not touch it. `fncli experiment down` removes it (with the release), and it waits while a project still uses it.

## 9. The GitHub demo with your own repo

fncli never creates or deletes GitHub repos, tokens or Apps. You make them, then your files point at them. The setup is described in [SETUP_GIT_APPS.md](SETUP_GIT_APPS.md).

1. Create the repo on GitHub, under an account or org you control. It must already have a commit on its default branch (tick "Add a README"). One repo plays both roles: the trigger repo and the results repo.

2. Create the GitHub App (Settings, Developer settings, GitHub Apps, New GitHub App. For an org, use the org's settings):
   - untick Webhook "Active";
   - Repository permissions: **Contents** and **Pull requests**, read and write;
   - "Only on this account", and leave the user-authorisation options off.

3. Note the **App ID** from the App's settings page. This is `GH_APP_ID`.

4. Generate a private key on the same page. Keep the `.pem` outside the repo (`.pem` is not gitignored):

   ```bash
   mkdir -p ~/.config/phems
   mv <where the browser saved it>/<app>.private-key.pem ~/.config/phems/<your-app>.private-key.pem
   chmod 600 ~/.config/phems/<your-app>.private-key.pem
   ```

5. Install the App, on only your repo. After the install, the number at the end of the installation URL is the **installation ID**. This is `GH_INSTALLATION_ID`.

6. Add the two ids to `.dev.env`, which is your context file's `node.env_file`. Use your own values, not the ones in the example's comments:

   ```bash
   GH_APP_ID=<your App ID>
   GH_INSTALLATION_ID=<your installation ID>
   ```

7. Give fncli a researcher token. The demo's pull requests into the trigger repo are your own work, not the node's, so they do not use the App. Pick one:
   - `gh auth login`, then check that `gh auth token` prints a token (it is read at run time); or
   - put `RESEARCHER_GIT_TOKEN=<token>` in `.dev.env`, a personal access token that can write to the repo.

   > TODO(verify): the repo only says "a personal access token that can write to the repo". For a fine-grained token, Contents and Pull requests with read and write on the repo should be enough.

8. Copy the example. The copy is yours: keep it out of git, or commit it with your own names.

   ```bash
   cp config/github/demo-github.yaml config/github/<your-name>-github.yaml
   ```

9. Edit the copy.

   | Change | Where | Rule |
   |---|---|---|
   | Repo uri `https://github.com/Aridhia-Open-Source/phems-sandbox` | both Repositories' `spec.uri`, and `repository:` under the project's `triggers` and `results` | Four places, all `https://github.com/<owner>/<repo>`: your repo |
   | NodeSecret name `phems-sandbox-creds` | the NodeSecret's `metadata.name`, and `spec.secret` of both Repositories | Three places. Lowercase letters, digits, `-` and `.` only |
   | Kubernetes Secret `phems-sandbox-github-app` | the NodeSecret's `spec.fromSecret.name`, and the `kubectl create secret` below | Any name you like, the same in both |
   | `watchDir`, `targetDir` | the project's `triggers` and `results` | Directories in your repo, for example `mgmt/requests/` and `mgmt/results/`. They must not overlap, because the results pull requests go to the same repo and must not look like triggers |
   | `baseBranch` | the same two places | Your repo's default branch, for example `main` |
   | Project name `demo-github` | the Project's `metadata.name` | Yours, and different from your Gitea project's |

   Leave the GitProvider (`uri: https://github.com`) and the dataset `demo-db`, for the reason in step 8. The ids and the key go into the Kubernetes Secret, never into the file.

10. Store the App's values in the Secret, apply, run the demo, delete.

    ```bash
    kubectl create secret generic phems-sandbox-github-app -n fn \
      --from-literal=APP_ID="$GH_APP_ID" --from-literal=INSTALLATION_ID="$GH_INSTALLATION_ID" \
      --from-file=PRIVATE_KEY=$HOME/.config/phems/<your-app>.private-key.pem
    kubectl apply -f config/github/<your-name>-github.yaml
    kubectl get fn -n fn
    fncli demo --project <your-project>
    kubectl delete -f config/github/<your-name>-github.yaml
    ```

    `GH_APP_ID` and `GH_INSTALLATION_ID` must be set in your shell, for example `set -a; source .dev.env; set +a`. The `kubectl delete` of the Secret itself is separate: `kubectl delete secret phems-sandbox-github-app -n fn`. The file has no Gitea section, so there are no Gitea repos to make. The demo asks the backend for a token for each repo and calls GitHub with it (the two `verify-git-secret` steps), then opens a pull request into your repo, merges it, and later merges the results pull request, which you can watch in your repo. Everything is also visible in the `Open:` addresses.

    The delete notes at the end of step 8 apply here too: nothing is deleted in your GitHub repo, and the dataset stays.

## 10. Troubleshooting

Only what the repo's scripts and docs already call out.

| What you see | What to do |
|---|---|
| fncli: `... is for kubectl context kind-fn, but the current one is ...` | `kubectl config use-context kind-fn` |
| fncli: `node.env_file ... not found` | The env file must exist in or above the context file's directory. Make `.dev.env` (step 4) |
| fncli: `context.yaml not found, as given or under bootstrap/ from here up` | `cp bootstrap/examples/context.yaml bootstrap/context.yaml` (step 5), or give `--context FILE` |
| `kubectl get fn -n fn` shows a row not synced | Read its `Message`: a Kubernetes Secret that is missing (`fncli gitea setup -f FILE`, or `kubectl create secret` for GitHub, step 9), a dataset that is not on the node (the `fncli experiment` steps in step 7), or a repository not applied yet |
| `The node cannot connect to the dataset's database` | `fncli experiment deploy`, then `fncli experiment seed demo` |
| `No experiments deployment: run fncli experiment deploy first` | `fncli experiment deploy` |
| `fncli: command not found` | Activate mise in your shell (step 2), then a new terminal. Or run `mise run setup` if you have not |
| `fncli experiment`: `No such command`, or `No module named 'fncli'` | Run `mise run setup` in this checkout (step 5). An old pipx copy: `pipx uninstall phems` |
| `Writing to a GitHub repo needs RESEARCHER_GIT_TOKEN, or gh auth login` | Step 9, item 7 |
| A merged pull request does nothing | `fncli sensor-status`. Sensors are stopped by default: `fncli start-sensor --group all` |
| `fncli demo`: `Project ... is not synced to the node yet` | `kubectl get fn -n fn` and read the `Message`. Fix what it names, `kubectl apply -f config/` again, then the demo |
| A demo step failed | Fix the cause and rerun with `fncli demo --project <your project> --from N` |
| `Connection refused` on localhost 5000, 4000 or 3000 | Tilt must be running (`tilt up --stream`). Check `tilt logs \| grep "Port forward"`, or forward by hand: `kubectl port-forward service/nexus-api 5000:5000 -n fn` |
| Helm will not render, or the chart's subcharts are missing | `mise run helm deps` |
| `mise run deploy`: `<FN_DATA_DIR> does not exist - run ./scripts/cluster.sh up first` | `mise run cluster up` first. The bind mount is set when the cluster is created |
| `mise run deploy`: `dev cluster is owned by ...` | Tear down from the owning worktree, or `mise run deploy --force-owner`. `mise run deploy-owner` shows the owner |
| `mise run deploy` fails on an existing release | It runs `helm upgrade --install`, so rerunning is safe. If the release is stuck, `mise run teardown` then `mise run deploy` |
| `stale postgres data` on reinstall | Postgres only reads its password when it first creates its data. Keep the password secret and the data, or delete both: `mise run teardown` does |
| Pods in `ImagePullBackOff`, or the chart fails with a missing `nodeId` or a wrong database host | A stale or hand-edited `dev.values.yaml`. Compare it with `dev.example.values.yml`: `nodeId` set, image tags `latest`, `db.host` equal to `db.<NAMESPACE>.svc` |
| `mise run teardown`: `No cluster reachable, so nothing was wiped` | `~/.fn/data` is still on disk. Delete it before you reinstall, or keep the password secrets that go with it |
| `mise run teardown`: `namespace fn is gone, so an earlier teardown already wiped /data` | Nothing to do. It is information |
| A resource stays `Terminating` after `kubectl delete` | A project outside the file still uses it (the repository of the other demo, say). `kubectl get fn -n fn` shows the operator's message. Delete that project first |
| A pod is stuck in `CrashLoopBackOff` | `kubectl describe pod <pod> -n fn` and `kubectl logs <pod> -n fn` |

## 11. Teardown and starting over

| Goal | Command |
|---|---|
| Remove the demo project from the node | `kubectl delete -f` its file in `config/` (steps 8 and 9) |
| Remove the release and all of its data, keep the cluster | `mise run teardown`, then `mise run deploy` again |
| Delete the cluster, keep the registries and their images | `mise run cluster down`, then `mise run cluster up` |
| Delete the cluster and the registries | `mise run cluster down --remove-registries` |
| Teardown, new cluster and deploy in one go | `mise run teardown && mise run cluster down && mise run cluster up && mise run deploy` |
| Remove the demo database release | `helm uninstall experiments -n experiments` (the secrets and database files stay, so a later `seed` gets the data back) |

- `mise run teardown` wipes the node's data and releases the cluster's owner. It keeps the `experiments` release, so the demo database survives it.
- After `mise run teardown` and `mise run deploy`, or the full reset above, run `tilt up --stream` again, then `fncli start-sensor --group all`, then the demo. Your `.dev.env`, `dev.values.yaml`, `bootstrap/context.yaml`, your files under `config/` and the App's key file are untouched. The node resources and Secrets in namespace `fn` go with the namespace: run `fncli gitea setup` and `kubectl apply` of step 8 or 9 again.
- After the full reset or a new cluster, run `fncli experiment deploy` again if `kubectl get pods -n experiments` shows nothing.
- `fncli experiment down` deletes every experiment's node project, then uninstalls the release, which removes the datasets' resources. `demo-db` stays `Terminating` while a demo project still uses it: run `kubectl delete -f config/demo.yaml` first.

- To start the demo database from empty: `kubectl delete ns experiments`, then delete `~/.fn/data/experiments`. Postgres owns it, so that needs root or the kind node.
