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

A local Federated Node on a kind cluster, with Gitea running inside it, a small demo database, and `fncli` on your PATH. `fncli apply` sets up one project from a node file: it stores the secrets, registers the git provider and repositories, and creates the project. `fncli demo` then walks a pull request through it, one confirmed step at a time: it opens and merges a pull request, waits for the task to run, and merges the results pull request. `fncli delete` cleans up. You run it twice: once on the in-cluster Gitea, and once on a GitHub repo of yours, with a GitHub App that you created.

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

Worktrees are optional. One dev cluster has one owner at a time, so a second worktree needs the first one torn down, or `FORCE_OWNER=1 make deploy`. To make a sibling worktree with your gitignored config copied over (`.dev.env`, `dev.values.yaml`, your files under `bootstrap/` and `triggers/`):

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


   Leave `CLUSTER_NAME=fn`, `NAMESPACE=fn`, `RELEASE_NAME=fn-dev` and `DOCKER_TAG=v1` as they are. They are written into more than this file: the Tiltfile allows only `kind-fn`, the context file names `kind-fn` and the node files name `gitea.fn.svc`, fncli translates only hosts ending in `fn.svc`, `scripts/portfwd.sh` uses `-n fn`, and the values file names `db.fn.svc` and tag `v1`. Your own names go in your own files under `bootstrap/` (steps 6, 8 and 9), not here.

   Leave the other `TEST_*` lines, `GITEA_API_URI`, `NEXUS_API_URL` and `KEYCLOAK_NAMESPACE` alone too. They describe the dev project of the e2e suites. `fncli demo` sets its own names from the project file.

   You add `GH_APP_ID`, `GH_INSTALLATION_ID` and optionally `RESEARCHER_GIT_TOKEN` in step 9.

3. Edit `k8s/federated-node/dev.values.yaml`.

   - `nodeId`: your own node name (any text). It is required, and names the node in the results it delivers.
   - `db.host` stays `db.fn.svc` and every `tag` stays `v1`: they must match `NAMESPACE` and `DOCKER_TAG`.
   - Gitea: the example's `gitea:` block already turns it on. The chart generates the admin password into the `gitea-admin` secret, so no password goes in the file.

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

   It claims the dev cluster, renders the chart as a check, builds and pushes every image to `localhost:5001` (including `demo-fn`, the demo's task image, so there is no separate build step; they are `docker buildx bake` targets in `docker-bake.hcl`), creates the namespace and the `keycloak-first-user` secret, then runs `helm install` (up to 10 minutes). The first run is slow because Docker has no cache yet. At the end it prints the database passwords the chart generated.

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

Make your context file. It says which node fncli works on, and which project and way `fncli trigger` uses when you do not say. Every command that talks to the node reads it; fncli finds `bootstrap/context.yaml` from the current directory up. It is gitignored, so it stays local.

```bash
cp bootstrap/examples/context.yaml bootstrap/context.yaml
```

The example matches this guide: `url: http://localhost:5000`, `kube_context: kind-fn`, `keycloak_namespace: keycloak`, `env_file: .dev.env`. Change `defaults.project` to the name of your project when you have one (steps 8 and 9). `FNCLI_DEFAULT_PROJECT` and `FNCLI_DEFAULT_TRIGGER_TYPE` in the shell win over `defaults:`, and a flag wins over both. A command that uses a default says so on its first line.

## 7. The demo database and the sensors

Both demos use one dataset, `demo-db`. It is a tiny Postgres in its own `experiments` release and namespace. `make experiments` calls `fncli`, so step 6 comes first.

```bash
make experiments deploy
fncli experiment seed demo
fncli experiment setup demo
```

- `up` installs the `experiments` release: a Postgres with a database, a role and a generated password secret for each experiment under `experiments/`. Safe to rerun.
- `seed demo` loads `cdm.person` (three rows) and an empty `results` schema into `demo-db`, as `demo_user`. Safe to rerun.
- `setup demo` checks `experiments/demo/dataset.yaml` against its `values.yaml`, then applies it (it needs your context file from step 6): the node gets the `demo-db` dataset and its secret. The demo project files only assign it, so run this before them.
- Check: `kubectl get pods -n experiments` shows the database `Running`.

Start the Dagster sensors. Every sensor starts stopped, and `fncli demo` does not start them. Without them a merged pull request is never picked up.

```bash
fncli start-sensor --group all
fncli sensor-status
```

After a new `make deploy` or `make teardown`, start them again.

## 8. The Gitea demo

The demo is two files: the global resources (the git provider, the OAuth-app secrets and the repositories) and the project, which only assigns them and the dataset from step 7.

1. Copy the examples. Your copies in `bootstrap/` are gitignored, so they stay local.

   ```bash
   mkdir -p bootstrap/projects
   cp bootstrap/examples/globals-gitea.yaml bootstrap/globals-<your-name>.yaml
   cp bootstrap/examples/projects/demo-gitea.yaml bootstrap/projects/<your-name>.yaml
   ```

2. Edit the copies. Names may use only lowercase letters, digits, `-` and `.`, because they become secret labels.

   | Change | Where | Rule |
   |---|---|---|
   | OAuth app names `demo-sensor` and `demo-results` | globals, `secrets:`, `gitea_oauth.app` | Gitea tells apps apart by name. The two must differ from each other, from `fn-sensor` and `fn-results` (the e2e project's), and from the stock demo's if you also run it |
   | Secret labels `demo-trigger-repo-creds` and `demo-results-repo-creds` | globals, the `secrets:` keys, and `secret:` under `repositories.triggers` and `repositories.results` | Change each label everywhere it appears |
   | Repo names `demo-trigger-repo` and `demo-results-repo` | globals, `repositories.triggers[0].uri` and `repositories.results[0].uri`; project, `repository:` under `triggers` and `results` | Four places across the two files. Keep the host `gitea.fn.svc:4000` and the owner `gitea_admin`. fncli creates the repos (`gitea.create_repositories`) |
   | Project name `demo-gitea` | project, `projects[0].name` | Yours, and different from your GitHub project's. Put it in `defaults.project` of your context file too |
   | `watch_dir`, `target_dir`, `base_branch` | project, `triggers` and `results` | Optional. Keep `main`. The two directories must not overlap |

   Leave the rest as it is: the `providers:` block, and the dataset `demo-db` in the project's `datasets:`. `demo-db` is the name of the database on the host, which the experiments chart creates, so renaming it makes the dataset unreachable.

3. See what it would do. This only reads. The project can only be diffed once its globals are on the node, so diff the globals first.

   ```bash
   fncli diff -f bootstrap/globals-<your-name>.yaml
   ```

   The first line names the node and the kubectl context. Each secret that would be created lists where its values come from and whether they are `set` or `missing`. From a directory other than the repo root, `-f globals-<your-name>.yaml` also works: a bare name is looked up under the nearest `bootstrap/`.

4. Set the node up. This is the only step that creates anything. The global resources first, then the project.

   ```bash
   fncli apply -f bootstrap/globals-<your-name>.yaml
   fncli apply -f bootstrap/projects/<your-name>.yaml
   ```

   Each prints its diff, asks, then makes the Gitea repos, secrets, git provider and repositories, and then the project. Run the diffs again afterwards: they should show nothing left to change.

5. Run the guided demo. The trigger file is the JSON the pull request adds: `triggers/examples/demo.json` by default, `triggers/examples/demo-failing.json` for a task that fails. A path, or one relative to `triggers/`, works.

   ```bash
   fncli demo -f bootstrap/projects/<your-name>.yaml
   fncli demo -f bootstrap/projects/<your-name>.yaml triggers/examples/demo-failing.json
   ```

   The demo creates and deletes nothing. It first checks the plan, and stops with the rows that differ unless the node already matches the project file: run the applies above first. Before each step it says what the step does and shows the equivalent command. Enter runs it, `s` skips it, `q` quits. After each step it prints `Open:` addresses for the browser and the objects that were made. The pull request step waits up to 5 minutes for the task to run. Useful options:

   - `-y` runs every step without asking.
   - `--from N` starts at step N, for example after a failed step.

   You can run the demo again as often as you like. The pull request step is `fncli trigger`, which you can also run alone: `fncli trigger triggers/examples/demo.json --merge --watch` triggers `defaults.project` of your context file by pull request, and says which defaults it used on its first line.

   For the Gitea web pages that the `Open:` lines point to, log in as `gitea_admin`.

   > TODO(verify): the password is the chart-generated `gitea-admin` secret, and `make show-db-passwords` should list it. Not confirmed on a fresh install.

6. Clean up.

   ```bash
   fncli delete -f bootstrap/projects/<your-name>.yaml                 # the project only
   fncli delete -f bootstrap/globals-<your-name>.yaml --all            # its repositories, secrets and provider
   ```

   - The Gitea repos and OAuth apps stay, and the next run reuses them.
   - The dataset `demo-db` is not in these files, so neither delete touches it. `fncli experiment teardown demo` removes it, and is refused while a project still uses it.

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

8. Copy the examples.

   ```bash
   mkdir -p bootstrap/projects
   cp bootstrap/examples/globals-github.yaml bootstrap/globals-<your-name>-github.yaml
   cp bootstrap/examples/projects/demo-github.yaml bootstrap/projects/<your-name>-github.yaml
   ```

9. Edit the copies.

   | Change | Where | Rule |
   |---|---|---|
   | Repo uri `https://github.com/Aridhia-Open-Source/phems-sandbox` | globals, `repositories.triggers[0].uri` and `repositories.results[0].uri`; project, `repository:` under `triggers` and `results` | Four places across the two files, all `https://github.com/<owner>/<repo>`: your repo |
   | Secret label `phems-sandbox-creds` | globals, the `secrets:` key, and `secret:` under `repositories.triggers` and `repositories.results` | Three places. Lowercase letters, digits, `-` and `.` only |
   | `PRIVATE_KEY: {file: ...}` | globals, `secrets:`, under your label | The path of your `.pem`. `~` works, and so does a path relative to the globals file |
   | `watch_dir`, `target_dir` | project, `triggers` and `results` | Directories in your repo, for example `mgmt/requests/` and `mgmt/results/`. They must not overlap, because the results pull requests go to the same repo and must not look like triggers |
   | `base_branch` | the same two places | Your repo's default branch, for example `main` |
   | Project name `demo-github` | project, `projects[0].name` | Yours, and different from your Gitea project's |

   Leave the `providers:` block (`api_uri` defaults to `https://api.github.com`) and the dataset `demo-db`, for the reason in step 8. The context file's `env_file: .dev.env` is where `GH_APP_ID` and `GH_INSTALLATION_ID` are read from; change it only if you keep them in another env file. It is searched for from the context file's directory up.

10. Diff, apply, demo, delete.

    ```bash
    fncli diff -f bootstrap/globals-<your-name>-github.yaml
    fncli apply -f bootstrap/globals-<your-name>-github.yaml
    fncli apply -f bootstrap/projects/<your-name>-github.yaml
    fncli demo -f bootstrap/projects/<your-name>-github.yaml
    fncli delete -f bootstrap/projects/<your-name>-github.yaml
    fncli delete -f bootstrap/globals-<your-name>-github.yaml --all
    ```

    In the diff, `GH_APP_ID`, `GH_INSTALLATION_ID` and the key file must say `set`. The globals file has no Gitea section, so apply makes no Gitea repos. The demo asks the backend for a token for each repo and calls GitHub with it (the two `verify-git-secret` steps), then opens a pull request into your repo, merges it, and later merges the results pull request, which you can watch in your repo. Everything is also visible in the `Open:` addresses.

    The delete notes at the end of step 8 apply here too: nothing is deleted in your GitHub repo, and the dataset stays.

## 10. Troubleshooting

Only what the repo's scripts and docs already call out.

| What you see | What to do |
|---|---|
| fncli: `... is for kubectl context kind-fn, but the current one is ...` | `kubectl config use-context kind-fn` |
| fncli: `node.env_file ... not found` | The env file must exist in or above the context file's directory. Make `.dev.env` (step 4) |
| fncli: `context.yaml not found, as given or under bootstrap/ from here up` | `cp bootstrap/examples/context.yaml bootstrap/context.yaml` (step 6), or give `--context FILE` |
| `Nothing was applied, these secret values cannot be read`, or `missing` in the diff | Set what it names: `GH_APP_ID` and `GH_INSTALLATION_ID` in `.dev.env`, the key file at the path in your globals file, and for the demo database the `make experiments` steps in step 7 |
| `The node cannot connect to the dataset's database` | `make experiments deploy`, then `fncli experiment seed demo` |
| `No experiments deployment: run fncli experiment deploy first` | `make experiments deploy` |
| `fncli: command not found` | `pipx ensurepath`, then a new terminal |
| `make experiments`: `No such command`, or `No module named 'fncli'` | Reinstall from this checkout (step 6) |
| `Writing to a GitHub repo needs RESEARCHER_GIT_TOKEN, or gh auth login` | Step 9, item 7 |
| A merged pull request does nothing | `fncli sensor-status`. Sensors are stopped by default: `fncli start-sensor --group all` |
| `fncli demo`: `The node does not match ... yet` | `fncli apply -f <your globals file>`, then `fncli apply -f <the project file>`, then the demo again |
| A demo step failed | Fix the cause and rerun with `fncli demo -f <the project file> --from N` |
| `Connection refused` on localhost 5000, 4000 or 3000 | Tilt must be running (`tilt up --stream`). Check `tilt logs \| grep "Port forward"`, or forward by hand: `kubectl port-forward service/nexus-api 5000:5000 -n fn` |
| Helm will not render, or the chart's subcharts are missing | `make helm_deps` |
| `make deploy`: `<FN_DATA_DIR> does not exist - run ./scripts/cluster.sh up first` | `make cluster up` first. The bind mount is set when the cluster is created |
| `make deploy`: `dev cluster is owned by ...` | Tear down from the owning worktree, or `FORCE_OWNER=1 make deploy`. `make deploy-owner` shows the owner |
| `make deploy` fails on an existing release | It runs `helm install`. Use `make upgrade`, or `make teardown` then `make deploy` |
| `stale postgres data` on reinstall | Postgres only reads its password when it first creates its data. Keep the password secret and the data, or delete both: `make teardown` does |
| Pods in `ImagePullBackOff`, or the chart fails with a missing `nodeId` or a wrong database host | A stale or hand-edited `dev.values.yaml`. Compare it with `dev.example.values.yml`: `nodeId` set, tags equal to `DOCKER_TAG`, `db.host` equal to `db.<NAMESPACE>.svc` |
| `make teardown`: `No cluster reachable, so nothing was wiped` | `~/.fn/data` is still on disk. Delete it before you reinstall, or keep the password secrets that go with it |
| `make teardown`: `namespace fn is gone, so an earlier teardown already wiped /data` | Nothing to do. It is information |
| `delete --all` ends with `Skipped, the backend refused` | A project outside the file still uses what it deletes (the repository of the other demo, say). Delete that project first |
| A pod is stuck in `CrashLoopBackOff` | `kubectl describe pod <pod> -n fn` and `kubectl logs <pod> -n fn` |

## 11. Teardown and starting over

| Goal | Command |
|---|---|
| Remove the demo project from the node | `fncli delete -f` its project file, then `fncli delete -f` its globals file with `--all` (steps 8 and 9) |
| Remove the release and all of its data, keep the cluster | `make teardown`, then `make deploy` again |
| Delete the cluster, keep the registries and their images | `make cluster down`, then `make cluster up` |
| Delete the cluster and the registries | `./scripts/cluster.sh down --remove-registries` (run it directly: `make` would take the flag for its own) |
| Teardown, new cluster and deploy in one go | `make nuke` |
| Remove the demo database release | `helm uninstall experiments -n experiments` (the secrets and database files stay, so a later `seed` gets the data back) |

- `make teardown` wipes the node's data and releases the cluster's owner. It keeps the `experiments` release, so the demo database survives it.
- After `make teardown` and `make deploy`, or `make nuke`, run `tilt up --stream` again, then `fncli start-sensor --group all`, then the demo. Your `.dev.env`, `dev.values.yaml`, `bootstrap/context.yaml`, your files under `bootstrap/` and the App's key file are untouched.
- After `make nuke` or a new cluster, run `make experiments deploy` again if `kubectl get pods -n experiments` shows nothing.
- `fncli experiment down` removes every experiment's dataset from the node, then the release. It stops while a demo project still uses `demo-db`: run `fncli delete -f bootstrap/projects/<your-name>.yaml` first.

- To start the demo database from empty: `kubectl delete ns experiments`, then delete `~/.fn/data/experiments`. Postgres owns it, so that needs root or the kind node.
