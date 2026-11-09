# Fresh setup: from an empty machine to the Gitea and GitHub demos

This guide takes a Linux or WSL2 machine with nothing installed, and a fresh clone, to a working `fncli demo` against both Gitea and GitHub. You use your own GitHub repo, your own GitHub App and your own names.

The source of truth is the repo: [DEPLOYMENT.md](DEPLOYMENT.md), [MANAGEMENT.md](MANAGEMENT.md), [SETUP_GIT_APPS.md](SETUP_GIT_APPS.md), [dagster/fncli/README.md](dagster/fncli/README.md) and [experiments/README.md](experiments/README.md). Where this guide could not be confirmed from the code, it says `TODO(verify)`.

- [1. What you end up with](#1-what-you-end-up-with)
- [2. Install the tools](#2-install-the-tools)
- [3. Clone](#3-clone)
- [4. Local config](#4-local-config)
- [5. Cluster and deploy](#5-cluster-and-deploy)
- [6. Install fncli](#6-install-fncli)
- [7. The demo database and the sensors](#7-the-demo-database-and-the-sensors)
- [8. The Gitea demo](#8-the-gitea-demo)
- [9. The GitHub demo with your own repo](#9-the-github-demo-with-your-own-repo)
- [10. Troubleshooting](#10-troubleshooting)
- [11. Teardown and starting over](#11-teardown-and-starting-over)

## 1. What you end up with

A local Federated Node on a kind cluster, with Gitea running inside it, a small demo database, and `fncli` on your PATH. `fncli demo` then walks one project from nothing to a merged pull request, one confirmed step at a time. It stores the secrets, registers the git provider and repositories, creates the project, opens and merges a pull request, waits for the task to run, and merges the results pull request. You run it twice: once on the in-cluster Gitea, and once on a GitHub repo of yours, with a GitHub App that you created.

## 2. Install the tools

You need these. The repo pins only two versions: Helm v3 and Python 3.12 or newer. It pins none for the rest, so use current releases.

| Tool | Why |
|---|---|
| `git`, `make`, `curl`, `jq` | clone, the Makefile, installers, scripts |
| Docker | builds the images, runs kind and the local registries |
| `kubectl`, `helm` (v3), `kind` | the cluster and the chart |
| `tilt` | the port-forwards fncli needs (nexus-api 5000, Gitea 4000, Dagster 3000), and live reload |
| Python 3.12+ and `pipx` | installs `fncli` |
| `gh` (optional) | gives fncli a GitHub token for the GitHub demo, if you do not set `RESEARCHER_GIT_TOKEN` |

1. Base packages (Debian, Ubuntu, WSL):

   ```bash
   sudo apt update
   sudo apt install -y git make curl jq pipx
   python3 --version        # must be 3.12 or newer
   ```

   If your `python3` is older, install 3.12 your own way and pass `--python python3.12` to `pipx install` in step 6.

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
   for t in git make curl jq docker kubectl helm kind tilt pipx; do command -v $t >/dev/null || echo "missing: $t"; done
   ```

## 3. Clone

```bash
git clone https://github.com/Aridhia-Open-Source/PHEMS_federated_node.git
cd PHEMS_federated_node
git checkout fncli-declarative-config
```

> TODO(verify): `fncli demo`, the demo node files and the demo database exist only on the `fncli-declarative-config` branch at the time of writing. Once it is merged, stay on the default branch instead.

Run every command from here on from the repo root, unless a step says otherwise.

Worktrees are optional. One dev cluster has one owner at a time, so a second worktree needs the first one torn down, or `FORCE_OWNER=1 make deploy`. To make a sibling worktree with your gitignored config copied over (`.dev.env`, `dev.values.yaml`, your `bootstrap/*.yaml`):

```bash
make worktree NAME=wt-mine BRANCH=my-branch [BASE=<ref>]
cd ../wt-mine
```

Then install fncli from it (step 6) and run `make helm_deps && make deploy`.

## 4. Local config

Two files, both gitignored. Do this before step 5: `scripts/cluster.sh` and `scripts/deploy.sh` read `.dev.env`.

1. Copy them.

   ```bash
   cp .dev.env.example .dev.env
   cp k8s/federated-node/dev.example.values.yml k8s/federated-node/dev.values.yaml
   ```

2. Edit `.dev.env`.

   | Variable | Set it to | Why |
   |---|---|---|
   | `KEYCLOAK_FIRST_USER_EMAIL` | your email | Your admin login for the API. `deploy.sh` stores it in the `keycloak-first-user` secret |
   | `KEYCLOAK_FIRST_USER_PASSWORD` | a password you will remember | Same. Quote it if it has special characters, because the file is `source`d by bash |
   | `TEST_PR_IMAGE` | `localhost:5001/demo-fn:latest` | The image of the spec in the demo's pull request. `make deploy` builds `demo-fn`. |

   > TODO(verify): `.dev.env.example` says `TEST_PR_IMAGE=localhost:5001/pypipes-fn:latest`, an image that `scripts/build_all_images.sh` does not build, and `fncli demo` does not override it. Deleting the line also works: `PrConfig` defaults to `demo-fn`.

   Leave `CLUSTER_NAME=fn`, `NAMESPACE=fn`, `RELEASE_NAME=fn-dev` and `DOCKER_TAG=v1` as they are. They are written into more than this file: the Tiltfile allows only `kind-fn`, the node files name `kind-fn` and `gitea.fn.svc`, fncli translates only hosts ending in `fn.svc`, `scripts/portfwd.sh` uses `-n fn`, and the values file names `db.fn.svc` and tag `v1`. Your own names go in the node files (steps 8 and 9), not here.

   Leave the other `TEST_*` lines, `GITEA_API_URI`, `NEXUS_API_URL` and `KEYCLOAK_NAMESPACE` alone too. They describe the dev project of the e2e suites. `fncli demo` sets its own names from the node file.

   You add `GH_APP_ID`, `GH_INSTALLATION_ID` and optionally `RESEARCHER_GIT_TOKEN` in step 9.

3. Edit `k8s/federated-node/dev.values.yaml`.

   - `nodeId`: your own node name (any text). It is required, and names the node in the results it delivers.
   - `db.host` stays `db.fn.svc` and every `tag` stays `v1`: they must match `NAMESPACE` and `DOCKER_TAG`.
   - Add Gitea. The example file has no `gitea:` block and the chart's default is `gitea.enabled: false`, so without this there is no Gitea, no `gitea-admin` secret, and no Gitea demo. Append at the top level:

     ```yaml
     gitea:
       enabled: true
       admin:
         user: gitea_admin
         email: admin@example.com
         secret:
           name: gitea-admin
           key: password
     ```

     The chart generates the admin password, so no password goes in the file.

     > TODO(verify): this is the block the author's own `dev.values.yaml` uses on top of the example. It was not confirmed with a fresh render. After `make helm_deps`, `make helm_template` renders the chart with the example file only, so run `helm template fn k8s/federated-node -f k8s/federated-node/dev.values.yaml` to check yours.

No CA files or `cadir` are needed: nothing in the repo's scripts, Tiltfile or chart reads them.

## 5. Cluster and deploy

1. Fetch the chart's subcharts. `charts/` is gitignored, so a fresh clone has none and Helm will not render.

   ```bash
   make helm_deps
   ```

2. Create the cluster and the registries.

   ```bash
   make cluster up
   ```

   It starts a registry at `localhost:5001` (your images) and two pull-through mirrors (`localhost:5002` Docker Hub, `localhost:5003` GHCR), then a kind cluster `fn` with the kubectl context `kind-fn`. Local volumes live in `~/.fn/data` (`FN_DATA_DIR`, fixed when the cluster is created).

3. Build the images and install the chart.

   ```bash
   make deploy
   ```

   It claims the dev cluster, renders the chart as a check, builds and pushes every image to `localhost:5001` (including `demo-fn`, the demo's task image, so there is no separate build step), creates the namespace and the `keycloak-first-user` secret, then runs `helm install` (up to 10 minutes). The first run is slow because Docker has no cache yet. At the end it prints the database passwords the chart generated.

   `make deploy` runs `helm install`, so a second run on a live release fails. Use `make upgrade` for chart changes, or `make teardown` first (step 11). It also stops a running Tilt, so deploy first and start Tilt after.

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

   `make portfwd` also forwards some of these, but not Gitea, so use Tilt.

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

## 6. Install fncli

```bash
pipx ensurepath          # then open a new terminal
pipx install --force --editable './dagster[cli]'
fncli hello-world        # Hello, world!
```

The editable install points at the checkout it was run from. To use another checkout or worktree, run the same `pipx install` from there. A stale one shows as `No module named 'fncli'`, or as commands missing.

fncli finds `.dev.env` by searching up from the current directory, so run it from inside the repo. It reads cluster secrets from the current kubectl context, which must be `kind-fn`.

## 7. The demo database and the sensors

Both demos use one dataset, `demo-db`. It is a tiny Postgres in its own `experiments` release and namespace. `make experiments` calls `fncli`, so step 6 comes first.

```bash
make experiments up
make experiments seed demo
```

- `up` installs the `experiments` release: a Postgres with a database, a role and a generated password secret for each project under `experiments/projects/`. Safe to rerun.
- `seed demo` loads `cdm.person` (three rows) and an empty `results` schema into `demo-db`, as `demo_user`. Safe to rerun.
- Check: `kubectl get pods -n experiments` shows the database `Running`.

Do not run `make experiments setup demo`: it looks for `bootstrap/examples/experiments/demo.yaml`, which does not exist. The demo node files register the dataset themselves.

> Planned, not built yet ([PLAN-experiment-bootstrap.md](dagster/fncli/PLAN-experiment-bootstrap.md), "Flow after"): `make experiments setup demo` will apply `experiments/projects/demo/bootstrap.yaml` after `seed`, and the demo node files will then drop their own dataset.

Start the Dagster sensors. Every sensor starts stopped, and `fncli demo` does not start them. Without them a merged pull request is never picked up.

```bash
fncli start-sensor --group all
fncli sensor-status
```

After a new `make deploy` or `make teardown`, start them again.

## 8. The Gitea demo

1. Copy the example. Your copy in `bootstrap/` is gitignored, so it stays local.

   ```bash
   cp bootstrap/examples/demo-gitea.yaml bootstrap/<your-name>.yaml
   ```

2. Edit the copy. Names may use only lowercase letters, digits, `-` and `.`, because they become secret labels.

   | Change | Where | Rule |
   |---|---|---|
   | OAuth app names `demo-sensor` and `demo-results` | `secrets:`, `gitea_oauth.app` | Gitea tells apps apart by name. The two must differ from each other, from `fn-sensor` and `fn-results` (the e2e project's), and from the stock demo's if you also run it |
   | Secret labels `demo-trigger-repo-creds` and `demo-results-repo-creds` | the `secrets:` keys, and `secret:` under `repositories.triggers` and `repositories.results` | Change each label everywhere it appears |
   | Repo names `demo-trigger-repo` and `demo-results-repo` | `repositories.triggers[0].uri`, `repositories.results[0].uri`, and `repository:` under the project's `triggers` and `results` | Four places. Keep the host `gitea.fn.svc:4000` and the owner `gitea_admin`. fncli creates the repos (`gitea.create_repositories`) |
   | Project name `demo-gitea` | `projects[0].name` | Yours, and different from your GitHub project's |
   | `watch_dir`, `target_dir`, `base_branch` | the project's `triggers` and `results` | Optional. Keep `main`. The two directories must not overlap |

   Leave the rest as it is: the `node:` block (it matches this guide's defaults), the `providers:` block, the `demo-db-dataset-creds` secret, and the `datasets:` block. `demo-db` is the name of the database on the host, which the experiments chart creates, so renaming it or its `host` or `k8s_secret` makes the dataset unreachable.

3. See what it would do. This only reads.

   ```bash
   fncli diff -f bootstrap/<your-name>.yaml
   ```

   The first line names the node and the kubectl context. Each secret that would be created lists where its values come from and whether they are `set` or `missing`. The demo database's two values must say `set`, or step 7 is not done. From a directory other than the repo root, `-f <your-name>.yaml` also works: a bare name is looked up under the nearest `bootstrap/`.

4. Run the guided demo.

   ```bash
   fncli demo -f bootstrap/<your-name>.yaml
   ```

   Before each step it says what the step creates and shows the equivalent command. Enter runs it, `s` skips it, `q` quits. After each step it prints `Open:` addresses for the browser and the objects that were made. The pull request step waits up to 5 minutes for the task to run. The last step offers to tear everything down, and the default is No. Useful options:

   - `-y` runs every step without asking, and leaves the teardown out.
   - `--from N` starts at step N, for example after a failed step.

   The demo is idempotent, so you can run it again.

   For the Gitea web pages that the `Open:` lines point to, log in as `gitea_admin`.

   > TODO(verify): the password is the chart-generated `gitea-admin` secret, and `make show-db-passwords` should list it. Not confirmed on a fresh install.

5. Clean up.

   ```bash
   fncli delete -f bootstrap/<your-name>.yaml            # the project only
   fncli delete -f bootstrap/<your-name>.yaml --all      # also its global repositories, dataset, secrets and provider
   ```

   - The Gitea repos and OAuth apps stay, and the next run reuses them.
   - Both demo files share `demo-db` and `demo-db-dataset-creds`. While the other demo's project still exists, `--all` skips those two with the backend's reason and exits 1. That is expected. Delete both projects with `--all` and the second run removes them.

## 9. The GitHub demo with your own repo

fncli never creates or deletes GitHub repos, tokens or Apps. You make them, then the node file points at them. The setup is described in [SETUP_GIT_APPS.md](SETUP_GIT_APPS.md).

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

6. Add the two ids to `.dev.env`, which is the node file's `node.env_file`. Use your own values, not the ones in the example's comments:

   ```bash
   GH_APP_ID=<your App ID>
   GH_INSTALLATION_ID=<your installation ID>
   ```

7. Give fncli a researcher token. The demo's pull requests into the trigger repo are your own work, not the node's, so they do not use the App. Pick one:
   - `gh auth login`, then check that `gh auth token` prints a token (it is read at run time); or
   - put `RESEARCHER_GIT_TOKEN=<token>` in `.dev.env`, a personal access token that can write to the repo.

   > TODO(verify): the repo only says "a personal access token that can write to the repo". For a fine-grained token, Contents and Pull requests with read and write on the repo should be enough.

8. Copy the example.

   ```bash
   cp bootstrap/examples/demo-github.yaml bootstrap/<your-name>-github.yaml
   ```

9. Edit the copy.

   | Change | Where | Rule |
   |---|---|---|
   | Repo uri `https://github.com/Aridhia-Open-Source/phems-sandbox` | `repositories.triggers[0].uri`, `repositories.results[0].uri`, and `repository:` under the project's `triggers` and `results` | Four places, all `https://github.com/<owner>/<repo>`: your repo |
   | Secret label `phems-sandbox-creds` | the `secrets:` key, and `secret:` under `repositories.triggers` and `repositories.results` | Three places. Lowercase letters, digits, `-` and `.` only |
   | `PRIVATE_KEY: {file: ...}` | `secrets:`, under your label | The path of your `.pem`. `~` works, and so does a path relative to the node file |
   | `watch_dir`, `target_dir` | the project's `triggers` and `results` | Directories in your repo, for example `mgmt/requests/` and `mgmt/results/`. They must not overlap, because the results pull requests go to the same repo and must not look like triggers |
   | `base_branch` | the same two places | Your repo's default branch, for example `main` |
   | Project name `demo-github` | `projects[0].name` | Yours, and different from your Gitea project's |
   | `node:` block | top of the file | `url: http://localhost:5000`, `kube_context: kind-fn`, `keycloak_namespace: keycloak`, `env_file: .dev.env`. These match this guide's defaults, so leave them. Change `env_file` only if you keep `GH_APP_ID` and `GH_INSTALLATION_ID` in another env file. It is searched for from the node file's directory up |

   Leave the `providers:` block (`api_uri` defaults to `https://api.github.com`), the `demo-db-dataset-creds` secret and the `datasets:` block, for the reason in step 8.

10. Diff, demo, delete.

    ```bash
    fncli diff -f bootstrap/<your-name>-github.yaml
    fncli demo -f bootstrap/<your-name>-github.yaml
    fncli delete -f bootstrap/<your-name>-github.yaml --all
    ```

    In the diff, `GH_APP_ID`, `GH_INSTALLATION_ID` and the key file must say `set`. This file has no Gitea section, so the demo has no "Create the Gitea repos" step, and its step numbers are one lower than the Gitea demo's. The demo asks the backend for a token for each repo and calls GitHub with it (the two `verify-git-secret` steps), then opens a pull request into your repo, merges it, and later merges the results pull request, which you can watch in your repo. Everything is also visible in the `Open:` addresses.

    The delete notes at the end of step 8 apply here too: nothing is deleted in your GitHub repo, and the shared dataset is skipped while the other demo's project exists.

## 10. Troubleshooting

Only what the repo's scripts and docs already call out.

| What you see | What to do |
|---|---|
| fncli: `... is for kubectl context kind-fn, but the current one is ...` | `kubectl config use-context kind-fn` |
| fncli: `node.env_file ... not found` | The env file must exist in or above the node file's directory. Make `.dev.env` (step 4) |
| `Nothing was applied, these secret values cannot be read`, or `missing` in the diff | Set what it names: `GH_APP_ID` and `GH_INSTALLATION_ID` in `.dev.env`, the key file at the path in your node file, and for the demo database the `make experiments` steps in step 7 |
| `The node cannot connect to the dataset's database` | `make experiments up`, then `make experiments seed demo` |
| `No experiments deployment: run fncli experiment up first` | `make experiments up` |
| `fncli: command not found` | `pipx ensurepath`, then a new terminal |
| `make experiments`: `No such command`, or `No module named 'fncli'` | Reinstall from this checkout (step 6) |
| `Writing to a GitHub repo needs RESEARCHER_GIT_TOKEN, or gh auth login` | Step 9, item 7 |
| A merged pull request does nothing | `fncli sensor-status`. Sensors are stopped by default: `fncli start-sensor --group all` |
| A demo step failed | Fix the cause and rerun with `fncli demo -f ... --from N` |
| `Connection refused` on localhost 5000, 4000 or 3000 | Tilt must be running (`tilt up --stream`). Check `tilt logs \| grep "Port forward"`, or forward by hand: `kubectl port-forward service/nexus-api 5000:5000 -n fn` |
| Helm will not render, or the chart's subcharts are missing | `make helm_deps` |
| `make deploy`: `<FN_DATA_DIR> does not exist - run ./scripts/cluster.sh up first` | `make cluster up` first. The bind mount is set when the cluster is created |
| `make deploy`: `dev cluster is owned by ...` | Tear down from the owning worktree, or `FORCE_OWNER=1 make deploy`. `make deploy-owner` shows the owner |
| `make deploy` fails on an existing release | It runs `helm install`. Use `make upgrade`, or `make teardown` then `make deploy` |
| `stale postgres data` on reinstall | Postgres only reads its password when it first creates its data. Keep the password secret and the data, or delete both: `make teardown` does |
| Pods in `ImagePullBackOff`, or the chart fails with a missing `nodeId` or a wrong database host | A stale or hand-edited `dev.values.yaml`. Compare it with `dev.example.values.yml`: `nodeId` set, tags equal to `DOCKER_TAG`, `db.host` equal to `db.<NAMESPACE>.svc` |
| `make teardown`: `No cluster reachable, so nothing was wiped` | `~/.fn/data` is still on disk. Delete it before you reinstall, or keep the password secrets that go with it |
| `make teardown`: `namespace fn is gone, so an earlier teardown already wiped /data` | Nothing to do. It is information |
| `delete --all` ends with `Skipped, the backend refused` | The other demo's project still uses the shared dataset. Expected (step 8) |
| A pod is stuck in `CrashLoopBackOff` | `kubectl describe pod <pod> -n fn` and `kubectl logs <pod> -n fn` |

## 11. Teardown and starting over

| Goal | Command |
|---|---|
| Remove the demo project from the node | `fncli delete -f bootstrap/<your-name>.yaml --all` (steps 8 and 9) |
| Remove the release and all of its data, keep the cluster | `make teardown`, then `make deploy` again |
| Delete the cluster, keep the registries and their images | `make cluster down`, then `make cluster up` |
| Delete the cluster and the registries | `./scripts/cluster.sh down --remove-registries` (run it directly: `make` would take the flag for its own) |
| Teardown, new cluster and deploy in one go | `make nuke` |
| Remove the demo database release | `helm uninstall experiments -n experiments` (the secrets and database files stay, so a later `seed` gets the data back) |

- `make teardown` wipes the node's data and releases the cluster's owner. It keeps the `experiments` release, so the demo database survives it.
- After `make teardown` and `make deploy`, or `make nuke`, run `tilt up --stream` again, then `fncli start-sensor --group all`, then the demo. Your `.dev.env`, `dev.values.yaml`, `bootstrap/<your-name>*.yaml` and the App's key file are untouched.
- After `make nuke` or a new cluster, run `make experiments up` again if `kubectl get pods -n experiments` shows nothing.
- `make experiments down` is the repo's own command for removing the demo database release, but it tears down every project under `experiments/projects/` first, and for `demo` it stops with `No node file for demo` because `bootstrap/examples/experiments/demo.yaml` does not exist. That is why the table uses `helm uninstall`.

  > TODO(verify): confirm `make experiments down` fails this way on a clean checkout. [PLAN-experiment-bootstrap.md](dagster/fncli/PLAN-experiment-bootstrap.md) step 5 plans to fix it.

- To start the demo database from empty: `kubectl delete ns experiments`, then delete `~/.fn/data/experiments`. Postgres owns it, so that needs root or the kind node.
