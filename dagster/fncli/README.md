# fncli

Dev tooling for the Federated Node: a click CLI that sets a dev node up from node files (Gitea, nexus-api
project and the trigger repository the git sensor builds on), triggers tasks with a trigger file, and checks the result. New commands go in
`cmds/` and are registered in `cli.py`.

## Requirements

- Python 3.12 or newer
- A working kubeconfig pointing at the dev cluster (the commands read secrets from it)
- For the apply, delete, trigger and demo commands: the Tilt port-forwards running, so nexus-api
  (`localhost:5000`) and Gitea (`localhost:4000`) are reachable

## Install

fncli is installed by `mise run setup`, from the repo root. It goes editable into `.venv` at the repo root, so changes to `dagster/fncli` take effect straight away. With [mise activated in your shell](https://mise.jdx.dev/getting-started.html#activate-mise), `fncli` is on your `PATH` anywhere in the repo. Without activation, `mise exec -- fncli` works.

```bash
mise run setup
fncli hello-world
```

It should print `Hello, world!`. If the shell says `fncli: command not found`, mise is not activated in it, or you are outside the repo.

The install belongs to that checkout, so a worktree needs its own `mise run setup`. If you installed fncli with pipx before, remove that copy so it does not answer instead: `pipx uninstall phems`.

## Usage

Run commands from anywhere inside the repo: `.dev.env` is found by searching up from the current directory. `fncli --help` lists the commands. fncli reads secrets from the CURRENT kubectl context, which must be `kind-fn`.

### Quick start

Three kinds of file, none with a secret value:

- **The context** (`bootstrap/context.yaml`, from `bootstrap/examples/context.yaml`): which node fncli works on (its url, the kubectl context it must be on, its env file) and the `defaults` of the commands. Every command that talks to the node reads it. It is found from the current directory up, or give `--context FILE` (`FNCLI_CONTEXT`). Without one the command stops and tells you to copy the example.
- **Node files** (`bootstrap/*.yaml`, `bootstrap/projects/*.yaml`, examples in `bootstrap/examples/`; `-f` takes a path, or one relative to the nearest `bootstrap/`): any of the providers, secrets, repositories, datasets and projects. The global resources are in one file and a project in another, so a project file is only its name and what it is assigned, by name. What a file names and does not hold must be on the node already, and the diff blocks what is nowhere. Each secret value says where it is read from (an env var, a file, a cluster secret, a random value, or a Gitea OAuth app fncli makes). [DESIGN-node-file.md](DESIGN-node-file.md) has the design.
- **Trigger files** (`triggers/*.json`, examples in `triggers/examples/`; a path, or one relative to the nearest `triggers/`): the JSON that asks the node to run a task, `{"spec": {"image": "...", "env": {...}}}`, the same file whether it is sent in a pull request or (later) to the API.

```bash
cp bootstrap/examples/context.yaml bootstrap/context.yaml
fncli diff  -f examples/globals-e2e.yaml    # what applying it would change on the node; reads only
fncli apply -f examples/globals-e2e.yaml    # print that, ask, build the global resources of the dev project
fncli apply -f examples/projects/e2e.yaml   # then the project
fncli start-sensor --group all      # ingest -> evaluate -> launcher, plus the run-status sensors (fncli sensor-status to watch)
fncli trigger triggers/examples/demo.json --project fn-dev --pr --merge   # a task, by a merged pull request
fncli delete -f examples/projects/e2e.yaml; fncli delete -f examples/globals-e2e.yaml --all   # delete it all again, last (Gitea repos stay)
fncli demo -f examples/projects/demo-gitea.yaml [TRIGGER] [-y] [--from N]   # on an applied node: the pull request walk, one confirmed step at a time (see Demo)
```

- `diff -f FILE [--project P]`: the difference between the file and the node, one row per entity (`+` create, `~` change, `=` unchanged, `!` needs a confirmation, `x` blocked, `?` checked at apply). Secrets can only be "exists", never "changed", and a secret to be created lists where each value is read from and whether it can be. `plan` is a hidden alias.
- `apply -f FILE [--project P] [-y] [--rotate LABEL]`: prints the diff, asks, then does it in order: secrets, providers, Gitea repos (if the file has a `gitea:` section), repositories, datasets, projects (created disabled, enabled last). It stops at the first backend error and says what was done and what was not. A secret is only written when missing (`--rotate LABEL` rewrites it, and authorises a Gitea OAuth app again, which rotates the app's client secret). An assignment that exists is only PATCHed with the fields that differ. A results repository on a live project is assigned by disabling the project and enabling it again, which the question mentions. What the backend refuses (a swapped results repository, another default dataset) is skipped with its manual steps and apply exits 1. Nothing is deleted.
- `delete -f FILE [--all] [-y]`: deletes the file's projects (their assignments go with them). With `--all` also the global repositories and datasets, then the secrets (with their stored values) and the providers, as far as the node has them, through the DELETE routes and never with `?force=true`: what a project outside the file still uses is skipped with the backend's message and delete exits 1. A provider that repositories outside the file are on is kept. Gitea repos and OAuth apps are left in place.
- `trigger FILE [--project P] [--pr | --api] [--merge] [--watch] [--timeout N]`: asks the node to run a task with a trigger file. With `--pr`, it adds the file in a new branch and a PR under the watch directory of the project's trigger repository (taken from the project's record in the node, not from the env), and with `--merge` merges the PR, which is what the sensor picks up; with `--watch` it then follows the PR, its task and its run. `--api` is reserved for sending the same file to the task API and says it is not built yet. The project and the way default to the context's `defaults` (`project`, `trigger_type`), `FNCLI_DEFAULT_PROJECT` and `FNCLI_DEFAULT_TRIGGER_TYPE` in the env win over those, and a flag wins over both. When a default is used, the first line of the output says which: `Using the defaults of bootstrap/context.yaml: project demo-gitea, via pr`. So with the defaults set, `fncli trigger triggers/examples/demo.json --merge --watch` is enough.
- `open-pr [--kind watched|unwatched|invalid|failing] [--merge] [--trigger FILE]`: the end-to-end checks' version of the same, on `--project` (else the context's default) and able to open the kinds of pull request the sensor must ignore or reject (see the pull request commands). Use `trigger` for your own work.

Each of the first three first checks that kubectl points at the context's `node.kube_context`, because it reads cluster secrets from the current one. The context's `node.env_file` is loaded first (found from the context file's directory up, like `.dev.env`), which is where a node file that refers to env vars (`{env: GH_APP_ID}`) finds them. A Gitea repository in a file must be under the context's `node.gitea_admin_user`.

Secrets, datasets and the trigger and results repositories are global: they belong to no project. A project is two repos (the trigger repo the sensor watches, and the results repo task results go to), a dataset, and a secret for each; the project only holds assignments of the global ones. Every step is idempotent and can be re-run after a failure.

### Step commands, by entity

**Project** (`cmds/project.py`)

| Command | What it does |
|---|---|
| `project-healthcheck` | Prints nexus-api's healthcheck for the project as JSON (can the repos be reached with their tokens?). Exits 1 unless the status is `ok` |

**Secret** (`cmds/secret.py`)

| Command | What it does |
|---|---|
| `verify-git-secret [--entity]` | Asks nexus-api for a token for the repo (`POST /global/repositories/{triggers,results}/{id}/token`, so the repo must be registered) and checks the provider accepts it |

**Pull request** (`cmds/pr.py`; the file name, branch and title carry a timestamp, so it can be re-run)

| Command | What it does |
|---|---|
| `create-gitea-branch [--branch]` | Branches off the repo's default branch |
| `commit-gitea-file --branch [--kind] [--trigger FILE]` | Commits one new file to the branch: the trigger file (default `triggers/examples/demo.json`), changed by the kind |
| `create-gitea-pr --branch [--kind]` | Opens the PR into the default branch |
| `merge-gitea-pr --number` | Merges the PR; the sensor only picks up merged PRs |
| `merge-results-pr --number` | Merges a results PR in the results repo; the sync sensor then records it as MERGED |

`--kind` picks the file, and so what the sensor makes of the PR: `watched` (default) is the trigger file as a new
`.json` spec file under the watch_dir, which becomes a task; `unwatched` is a file
outside the watch_dir, so the PR creates no trigger; `invalid` is the trigger file under the watch_dir
with an unknown field added to its spec, so the PR is rejected; `failing` adds `PYPIPES_EXIT_CODE=1` to its env, so the task fails.
`fncli trigger` runs the same steps for a project, always `watched`.

**Sensors** (`cmds/sensor.py`; needs the Dagster webserver on `DAGSTER_URL`, default `http://localhost:3000`)

| Command | What it does |
|---|---|
| `start-sensor (--group G \| --name N)` | Starts Dagster sensors. Give one of the two. `--group` is `ingest` (`git_pull_request_ingest_sensor`), `evaluate` (`git_pull_request_evaluate_sensor`), `launcher` (`task_launcher_sensor`), `status` (the five run-status sensors and `task_reconcile_sensor`), `delivery` (`task_results_delivery_sensor`, `results_pull_request_sync_sensor`, `results_delivery_retry_sensor`) or `all` (the twelve). `--name` is one sensor by its Dagster name, e.g. `task_reconcile_sensor` |
| `stop-sensor (--group G \| --name N)` | Stops them, the same choices; a group stops in reverse order, so `all` stops the launcher first |
| `sensor-status` | Prints every sensor's status and last 3 ticks (status, skip reason or error) |

Everything is STOPPED in Dagster by default. The whole path from a merged PR is: `ingest` polls the repository once and stores the PR, which nexus-api fans out to every project assigned to the repository (a trigger per assignment, UNKNOWN), `evaluate` turns each into a task (YIELDED, or REJECTED with a cause), `launcher`
starts a Dagster run for each PENDING task, and the run-status sensors copy the run's status onto the
task. The reconcile sensor sets every unfinished task to the current status of its run on each tick,
so the start order of the sensors does not matter. `start-sensor --group all` starts them all.

`hello-world` prints a greeting, to check the CLI is installed.

`verify-git-secret` and `delete-gitea-token` take `--project NAME` (else the context's `defaults.project`). The repo and its secret label come from nexus-api project's own trigger or results repository record: the repo is the last uri segment (its `repo_path` is `owner/name`), which must sit under the Gitea admin user (otherwise the command fails), and the secret is the record's. The command fails with a clear message if the project is missing or does not have exactly one record of that kind.

`--entity` is `trigger` (default) or `results`.

Every command that works on a project (`open-pr`, the PR steps, `verify-*`, `project-*`, `resource-set`, `global-set`, `secret-set`, `verify-git-secret`, ...) takes `--context FILE` and `--project NAME`. The context file says how to reach the node (`node.url`, `node.keycloak_namespace`, `node.gitea_admin_user`, `node.kube_context`) and, as `defaults.project` (or `FNCLI_DEFAULT_PROJECT`), which project to use when `--project` is not given; the first line says when it is used, and a command with neither fails. The project's repositories, branches, directories and datasets are read from the node, so there are no `TEST_*`, `NEXUS_API_URL`, `KEYCLOAK_NAMESPACE`, `GITEA_*` or `DEFAULT_PROJECT_DATASET` variables: `.dev.env` holds only the deploy settings, the first Keycloak user and the optional GitHub ids. What a task is asked to run is never in the env: it is the trigger file.

## State and rules (for the end-to-end suites)

The suites in [tests/e2e](tests/e2e/README.md) use these to look at the test project and to change the state nexus-api's rules act on.
Every write prints the HTTP status and body; `--expect STATUS` asserts the status (exit 1 if it differs), which is how the suites
check the 409 rules. `KIND` is `trigger`, `results`, `dataset` or `secret`; `--project NAME` picks another project.

| Command | What it does |
|---|---|
| `project-show [--project]` | JSON of the project's resources (enabled, revoked, active), their pull requests (state, task), tasks and results. Read-only; stdout is clean JSON, so it pipes into `jq` |
| `project-set [--enabled true\|false] [--revoked true\|false] [--backfill]` | Enables or disables the project, or revokes or restores it (admin only) (`PATCH /projects/<id>`). A new project is disabled; enabling it skips the pull requests stored while it was off, unless `--backfill` (with `--enabled true`, on a disabled project) creates their triggers |
| `resource-set KIND --enabled/--revoked true\|false [--target-dir DIR] [--base-branch BRANCH]` | Sets the flags of the project's resource for a global resource. `--revoked` is admin only and immediate. `--target-dir` is for the results resource, `--base-branch` for the trigger or results resource |
| `global-set KIND [--enabled true\|false] [--revoked true\|false]` | Turns the global resource behind the project's resource on or off; `--revoked` (admin only, trigger and results) withdraws it from every project |
| `secret-set [--entity trigger\|results\|dataset] --enabled true\|false` | Turns a secret on or off. Off also disables the repositories and datasets that use it, and they stay off when it is turned on |

A second project on the same global resources is `fncli apply -f examples/projects/e2e-second-projects.yaml --project QaTwo -y`, and `fncli delete -f examples/projects/e2e-second-projects.yaml -y` removes it (every project in that file that exists).

## Demo

`fncli demo -f PROJECT_FILE [TRIGGER]` walks the pull request process on a node that `fncli apply` has already set up with the project file (and the global files it refers to), and proves it works: checks that the node can log in to the dataset's database and the git host, a merged pull request that adds the trigger file, its task and its results pull request, then checks of the whole project. It creates and deletes nothing. The flow is `fncli apply -f GLOBALS`, `fncli apply -f PROJECT_FILE`, then `fncli demo -f PROJECT_FILE` (as often as you like), then `fncli delete -f PROJECT_FILE` and `fncli delete -f GLOBALS --all`. First it builds the plan `fncli diff` prints for the project file and stops with exit 1, listing the rows, unless nothing is left to change (Gitea repos that apply would ensure do not count). Before each step it says what the step does, shows the equivalent fncli command and asks: Enter runs it, `s` skips it, `q` quits. Steps are separated by a line of dashes. After each step it lists nexus-api calls it made (`METHOD /path -> status`, repeats counted) and shows what the step made: links to open in the browser (`Open:` lines) and nexus-api objects as JSON. A step that changes the project waits for the change to show in the project's state, polling every second, and prints it when it changes.

```bash
fncli apply -f examples/globals-gitea.yaml           # first: set the node up
fncli apply -f examples/projects/demo-gitea.yaml
fncli demo -f examples/projects/demo-gitea.yaml      # step by step, with triggers/examples/demo.json
fncli demo -f examples/projects/demo-github.yaml -y  # every step without asking, on GitHub (phems-sandbox)
fncli demo -f examples/projects/demo-gitea.yaml triggers/examples/demo-failing.json   # a task that fails
fncli demo -f examples/projects/demo-gitea.yaml --from 5   # start at step 5, e.g. after a step failed
fncli delete -f examples/projects/demo-gitea.yaml; fncli delete -f examples/globals-gitea.yaml --all    # last: clean up
```

It needs the dev cluster with Tilt running and the Dagster sensors already running, and the demo database (`fncli experiment deploy`, `seed demo` and `setup demo`). The demo's names are the project file's: its one project (`--project` picks one when there are several, else the context's `defaults.project`, which the first line says), with that project's first trigger repository, results repository and dataset, so it never touches the e2e project. The repositories' hosts and providers are read from the node, since a project file holds none. It can be rerun. The pull request step is `fncli trigger --pr --merge --watch` with the trigger file.

On GitHub the repo must already exist, and the globals file's secret reads `GH_APP_ID` and `GH_INSTALLATION_ID` from the context's `node.env_file` (`.dev.env`) and the App's private key from a file ([SETUP_GIT_APPS.md](../../SETUP_GIT_APPS.md)); the backend mints installation tokens from them. fncli works out the provider from the node. Everything the node does (reading the repos, `verify-git-secret`, `merge-results-pr`) uses tokens the backend mints, built like Dagster's clients (`GitAPIFactory`). The trigger repo's branches, files and pull requests (`trigger`, `open-pr`, `create-gitea-branch`, `commit-gitea-file`, `create-gitea-pr`, `merge-gitea-pr`) are the researcher's work: on Gitea the admin login, on GitHub `RESEARCHER_GIT_TOKEN`, or else the token of `gh auth login`. fncli never creates or deletes GitHub repos, tokens or Apps.

## Real experiments

`fncli experiment` runs a real experiment against the dev node. Each experiment is a folder `experiments/NAME/`: its database for the chart (`values.yaml`), its dataset as a node file (`dataset.yaml`), its trigger file (`trigger.json`: the image, and anything else the task is asked for), and the settings of `run` in `project.env` (`RUN_TIMEOUT`), which wins over `.dev.env` and the shell. Its node project is in the node files `bootstrap/examples/globals-NAME.yaml` and `projects/NAME.yaml`, if it has them. Run it from inside the repo. `setup`, `run`, `teardown` and `down` talk to the node, so they need the context file (`--context`).

```bash
fncli experiment deploy              # install/upgrade the release: Postgres + every experiment's database
fncli experiment build NAME      # docker build + push of the image
fncli experiment seed NAME       # load the dummy data (recreates its schemas); needs `deploy`; safe to rerun
fncli experiment setup NAME      # check dataset.yaml against values.yaml, apply it (the dataset), then the globals and the project if it has them; needs `deploy`; safe to rerun
fncli experiment run NAME        # start-sensor, then trigger --pr --merge --watch with trigger.json; DEV_ENV in the shell is added to the task's env, FULL=1 leaves it out
fncli experiment run NAME --local  # the image of trigger.json in docker against the database, no node
fncli experiment teardown NAME   # delete NAME's node project, global resources and dataset (Gitea repos stay)
fncli experiment down            # teardown every experiment, then uninstall the release (secrets and database files stay)
```

`deploy` runs `helm upgrade --install` of the `experiments` release. `seed` and `setup` check it is installed (if not, they tell you to run `deploy`). `seed` runs the experiment's `seed.sh` over `kubectl exec` (which recreates its schemas). `setup` first checks that `dataset.yaml` names the database and secret of `values.yaml`, then runs `fncli apply` of it (the dataset, which reads the generated login from the chart's secret) and of the experiment's global and project files. See [experiments/README.md](../../experiments/README.md).

## Maintenance

After changing dependencies in `dagster/pyproject.toml`, or when a new command is missing or you get `No module named 'fncli'`, run `mise run setup` again from the checkout you want.

fncli's dependencies are the `cli` extra in `dagster/pyproject.toml`; its Dagster code is
`dagster/app`, shared with the code location.

## Uninstall

Delete `.venv` at the repo root. The `fncli` command goes with it, and your repo files are not touched.

An old pipx install is separate: `pipx uninstall phems` removes it. `pipx ensurepath` may have added a block to your shell config (a `# Created by pipx` comment in `~/.bashrc`); delete it by hand if nothing else you use needs it.

## Layout

```
dagster/fncli/
  cli.py            click group; loads .dev.env and registers commands
  cmds/             the commands
    common.py       env config classes and the Gitea and backend API builders
    nodefile.py     diff, apply and delete: the commands that work from a node file, and the context option
    demo.py         the pull request walk on an applied project file
    experiment.py   real experiments: release, seed, image, setup (apply), run, teardown (delete)
    trigger.py      trigger: a trigger file by pull request, or (later) by API
    actions.py      open-pr, the e2e checks' version of it
    project.py      the project healthcheck, and the find/init helpers the others use
    repository.py   Gitea repos and nexus-api repository records, for the simulation and the commands that read them
    secret.py       verify-git-secret, and the OAuth secret the simulation writes
    pr.py           the individual PR steps
    sensor.py       start/stop/status of the Dagster sensors
    hello_world.py  install check
  backend.py        FncliBackendAPI: app.backend.BackendAPI plus the create, update and delete calls apply and delete make
  nodefile/         the node file and the context file: schema, loader, diff, backend state, apply and delete executors
  gitea.py          Gitea admin client on top of app.gitea
  k8s.py            host-side kubeconfig loading
  sensors.py        the Dagster GraphQL client
```

fncli imports the shared client code and models from `app` (`app.backend`, `app.gitea`,
`app.models`, ...). Anything only the CLI needs lives here, never in `dagster/app`.

## Simulation (several providers, repositories and projects)

`fncli simulate-setup`, `simulate-run`, `simulate-check` and `simulate-teardown` run a multi-provider simulation on the dev cluster
(`fncli/cmds/simulate.py`, logic in `fncli/simulation.py`). Four projects (`SimOne` to `SimFour`) are assigned three trigger repositories and
two results repositories over two `GitProvider`s: the cluster's Gitea under its own name, and under an alias host `gitea-b` (a
Kubernetes ExternalName service the setup creates, so the providers' `uri` stay unique). One project watches repositories on both
providers, one repository is shared by two projects, and the projects deliver to different results repositories.
`simulate-run --seed N --prs-per-repo N` merges seeded pull requests (watched, invalid, unwatched and failing) in all trigger
repositories at once, waits for the sensors, then checks per project and repository: the right pull requests and tasks, no task shared
between projects, results delivered only to the project's own results repository. It writes a report to `artifacts/simulation/`.
It takes `--context` and needs the node's one Gitea provider (`fncli apply -f examples/globals-gitea.yaml`), whose address the simulation's two providers are made from, and `NAMESPACE` in `.dev.env`. It has not been run. Later: an outage step (break
one provider's token or `api_uri`), then retries.
