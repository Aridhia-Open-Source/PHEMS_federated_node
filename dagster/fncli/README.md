# fncli

Dev tooling for the Federated Node: a click CLI for the simulation work (setting up Gitea,
the backend project and the trigger repository the git sensor builds on). New commands go in
`cmds/` and are registered in `cli.py`.

## Requirements

- Python 3.12 or newer
- A working kubeconfig pointing at the dev cluster (the commands read secrets from it)
- For the setup, open-pr and teardown commands: the Tilt port-forwards running, so the backend
  (`localhost:5000`) and Gitea (`localhost:4000`) are reachable

## Install

### 1. Install pipx

pipx installs command-line tools into their own isolated environments and puts them on your
`PATH`, so `fncli` works from any shell without activating a virtualenv.

Debian, Ubuntu and WSL:

```bash
sudo apt install pipx
```

Anywhere else:

```bash
python3 -m pip install --user pipx
```

### 2. Put pipx's bin directory on your PATH

```bash
pipx ensurepath
```

This adds `~/.local/bin` to your shell config. **Open a new terminal afterwards** (or run
`source ~/.bashrc`) for it to take effect.

If `pipx ensurepath` says the directory is "already in PATH" but a fresh terminal still
cannot find your tools, the terminal is probably a non-login shell that only reads
`~/.bashrc`, not `~/.profile`. Either run `pipx ensurepath --force`, or add the line yourself:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 3. Install fncli

From the repo root:

```bash
pipx install --force --editable './dagster[cli]'
```

The pipx environment is named `phems` (the package name), the command is `fncli`.
`--editable` links to the source, so changes to `dagster/fncli` take effect straight away.
Without it, pipx installs a copy and you would need to reinstall after every edit.

### 4. Check it works

```bash
fncli hello-world
```

It should print `Hello, world!`. If the shell says `fncli: command not found`, go back to
step 2.

## Usage

Run commands from anywhere inside the repo: `.dev.env` is found by searching up from the current directory. `fncli --help` lists the commands. fncli reads secrets from the CURRENT kubectl context, which must be `kind-fn`.

### Quick start

```bash
fncli setup-project                 # build a whole dev project
fncli start-sensor --group all     # ingest -> evaluate -> launcher, plus the run-status sensors (fncli sensor-status to watch)
fncli open-pr [--kind watched|unwatched|invalid] [--merge]
fncli teardown-project -y           # delete it all again, last
fncli demo [-y] [--from N]          # the same, one confirmed step at a time (see Demo)

fncli setup-backend                 # or the two halves separately:
fncli setup-gitea [--project NAME]
fncli teardown-gitea -y [--project NAME]
fncli teardown-backend -y
```

- `setup-project`: builds the dev project. Side effects: creates two Gitea repos (trigger and results), a Gitea token for each (`fn-sensor`, `fn-results`), the K8s secrets holding them and the dataset's credentials (via the backend; dummies unless the `DATASET_*` env vars are set, see below), and the backend records: the project, the global git provider (the Gitea host), trigger repository, results repository and dataset, and the project's assignment of each. The project is created disabled and enabled at the end, once its links are set up.
- `open-pr`: opens a PR in the trigger repo for the sensor to find. Side effects: a new branch, one new file and a PR in Gitea; with `--merge` the PR is merged, which is what the sensor picks up.
- `teardown-project -y`: deletes the lot, side effects included: the backend project and its assignments, then the global dataset, repositories, git provider (unless another project's repositories are still on it) and secrets (backend and K8s), the Gitea tokens and both Gitea repos with all their PRs. `-y` skips the prompt.

- `setup-backend`: the backend only, no Gitea call. Side effects: the backend project, the three global secrets (K8s, holding placeholders: git secrets `{"TOKEN": "unset"}`, the dataset's credentials), the global git provider, trigger repository, results repository and dataset, and the project's assignment of each (the trigger one watching `main`). The project stays disabled: enable it with `project-set --enabled true` once `setup-gitea` has run.
- `setup-gitea`: the Gitea side of an existing backend project, which is the reference (not the `TEST_*_REPO` env vars). Side effects: creates the Gitea repos its trigger and results repository records name, issues a Gitea token for each (`fn-sensor`, `fn-results`), writes it into that record's existing secret and checks Gitea accepts it.
- `teardown-gitea -y`: deletes the Gitea tokens and repos (with all their PRs) named by the project's backend records. The backend is left alone.
- `teardown-backend -y`: deletes the project (with its assignments), then the global dataset, repositories and secrets (backend and K8s). Gitea is left alone.

Intended use: `setup-backend` then `setup-gitea`, or `setup-project` for both in one go (and `teardown-gitea` then `teardown-backend`, or `teardown-project`).

Secrets, datasets and the trigger and results repositories are global: they belong to no project. The `init-backend-*` commands create the global record if it is missing (found by uri, name or label), then assign it to the test project with `POST /projects/<id>/...`, so a re-run changes nothing. A project is two Gitea repos (`--entity trigger` is the repo the sensor watches, `--entity
results` is where task results go), a dataset, and a secret for each of the three. Every
step is its own command and the group commands chain them; every step is idempotent and can be run
on its own or re-run after a failure. Deletes of something already gone are logged, not errors.

### Group commands (`cmds/actions.py`)

| Command | What it does |
|---|---|
| `setup-project` | Runs, in order: `init-backend-project`, `init-gitea-repo` (trigger, results), `init-git-secret` (trigger, results), `init-dataset-secret`, `init-backend-trigger-repo`, `init-backend-results-repo`, `init-backend-dataset`, `verify-git-secret` (trigger, results), `project-set --enabled true`, `project-healthcheck` |
| `open-pr [--kind] [--merge]` | Runs `create-gitea-branch`, `commit-gitea-file`, `create-gitea-pr`, and with `--merge` `merge-gitea-pr` |
| `setup-backend` | Backend only, no Gitea: `init-backend-project`, `init-backend-secret` (trigger, results, dataset), `init-backend-trigger-repo --base-branch main`, `init-backend-results-repo`, `init-backend-dataset` |
| `teardown-backend [-y]` | Backend only: `delete-backend-project`, then `delete-backend-dataset`, `delete-backend-results-repo`, `delete-backend-trigger-repo`, `delete-secret` (trigger, results, dataset) |
| `setup-gitea [--project]` | Gitea only, repos taken from the project's backend records (`--from-backend`): `init-gitea-repo` (trigger, results), `init-git-secret` (trigger, results; writes into the record's secret), `verify-git-secret` (trigger, results) |
| `teardown-gitea [-y] [--project]` | Gitea only, same records: `delete-gitea-token` (trigger, results), `delete-gitea-repo` (trigger, results) |
| `teardown-project [-y]` | After asking (`-y` / `--yes` skips the prompt), runs: `delete-backend-project` first, then `delete-backend-dataset`, `delete-backend-results-repo`, `delete-backend-trigger-repo`, `delete-secret` (trigger, results, dataset), `delete-gitea-token` (trigger, results), `delete-gitea-repo` (trigger, results). Both Gitea repos are always deleted |

### Step commands, by entity

**Project** (`cmds/project.py`)

| Command | What it does |
|---|---|
| `init-backend-project` | Finds or creates the test project in the backend. A new project is disabled (a results repository can only be linked to a disabled project); enable it with `project-set --enabled true` |
| `delete-backend-project` | Deletes the project with its tasks, triggers and assignments (`DELETE /projects/<id>`). The global secrets, datasets and repositories stay |
| `project-healthcheck` | Prints the backend's healthcheck for the test project as JSON (can the repos be reached with their tokens?). Exits 1 unless the status is `ok` |

**Repository** (`cmds/repository.py`)

| Command | What it does |
|---|---|
| `init-gitea-repo [--entity]` | Finds or creates the repo in Gitea |
| `delete-gitea-repo [--entity] [-y]` | Deletes the repo from Gitea, after asking. Backend records are left alone |
| `init-backend-trigger-repo [--base-branch]` | Creates the global git provider (the Gitea host: the API's scheme and the repo uri's host) and then the global trigger repository on it if missing and assigns it to the project (watch_dir, base_branch), so the sensor polls it. Without `--base-branch` the branch is the repo's default branch in Gitea (a Gitea call) |
| `init-backend-results-repo` | Creates the global git provider if missing and then the global results repository on it if missing and assigns it to the project (target_dir) as its results repository |
| `delete-backend-trigger-repo`, `delete-backend-results-repo` | Delete that global repository from the backend, and with it every project's assignment of it. The trigger one is refused while any of its assignments has pull requests (delete the project first) |
| `delete-backend-provider` | Deletes the Gitea git provider from the backend, unless a repository (of any project) is still on it, in which case it is left. Run after the two repository deletes |

**Secret** (`cmds/secret.py`)

| Command | What it does |
|---|---|
| `init-git-secret [--entity]` | Stores a fresh Gitea token in the repo's K8s secret (`read:repository` for trigger, `write:repository` for results) |
| `init-backend-secret [--entity trigger\|results\|dataset]` | Creates the global secret in the backend (`POST /global/secrets`) with placeholder values (`{"TOKEN": "unset"}`, or the dataset's dummies), with no Gitea call. An existing secret is left alone, so a real token is never overwritten |
| `init-dataset-secret` | Stores `USERNAME` and `PASSWORD` (`DATASET_USERNAME`, `DATASET_PASSWORD`, default `dummy`) in the dataset's secret (`<dataset>-dataset-creds`) |
| `verify-git-secret [--entity]` | Checks Gitea accepts the token currently stored in the repo's secret |
| `delete-secret [--entity trigger\|results\|dataset]` | Deletes the global secret from the backend and K8s. Refused while a repo or dataset uses it |
| `delete-gitea-token [--entity]` | Deletes the Gitea token `init-git-secret` created for the repo |

**Dataset** (`cmds/dataset.py`)

| Command | What it does |
|---|---|
| `init-backend-dataset` | Creates the global dataset if missing (needs the dataset secret) and assigns it to the project. The first one assigned becomes the project's default |
| `delete-backend-dataset` | Soft deletes the global dataset in the backend, and revokes and deletes every project's assignment of it |

**Pull request** (`cmds/pr.py`; the file name, branch and title carry a timestamp, so it can be re-run)

| Command | What it does |
|---|---|
| `create-gitea-branch [--branch]` | Branches off the repo's default branch |
| `commit-gitea-file --branch [--kind]` | Commits one new file to the branch |
| `create-gitea-pr --branch [--kind]` | Opens the PR into the default branch |
| `merge-gitea-pr --number` | Merges the PR; the sensor only picks up merged PRs |
| `merge-results-pr --number` | Merges a results PR in the results repo; the sync sensor then records it as MERGED |

`--kind` picks the file, and so what the sensor makes of the PR: `watched` (default) is one
new `.json` spec file under the watch_dir, which becomes a task; `unwatched` is a file
outside the watch_dir, so the PR creates no trigger; `invalid` is a `.json` under the watch_dir
whose spec has an unknown field, so the PR is rejected.

**Sensors** (`cmds/sensor.py`; needs the Dagster webserver on `DAGSTER_URL`, default `http://localhost:3000`)

| Command | What it does |
|---|---|
| `start-sensor (--group G \| --name N)` | Starts Dagster sensors. Give one of the two. `--group` is `ingest` (`git_pull_request_ingest_sensor`), `evaluate` (`git_pull_request_evaluate_sensor`), `launcher` (`task_launcher_sensor`), `status` (the five run-status sensors and `task_reconcile_sensor`), `delivery` (`task_results_delivery_sensor`, `results_pull_request_sync_sensor`, `results_delivery_retry_sensor`) or `all` (the twelve). `--name` is one sensor by its Dagster name, e.g. `task_reconcile_sensor` |
| `stop-sensor (--group G \| --name N)` | Stops them, the same choices; a group stops in reverse order, so `all` stops the launcher first |
| `sensor-status` | Prints every sensor's status and last 3 ticks (status, skip reason or error) |

Everything is STOPPED in Dagster by default. The whole path from a merged PR is: `ingest` polls the repository once and stores the PR, which the backend fans out to every project assigned to the repository (a trigger per assignment, UNKNOWN), `evaluate` turns each into a task (YIELDED, or REJECTED with a cause), `launcher`
starts a Dagster run for each PENDING task, and the run-status sensors copy the run's status onto the
task. The reconcile sensor sets every unfinished task to the current status of its run on each tick,
so the start order of the sensors does not matter. `start-sensor --group all` starts them all.

`hello-world` prints a greeting, to check the CLI is installed.

The Gitea-facing steps (`init-gitea-repo`, `delete-gitea-repo`, `init-git-secret`, `verify-git-secret`, `delete-gitea-token`) also take `--from-backend` and `--project NAME`. By default the repo and its secret label come from the `TEST_*` env vars. With `--from-backend` they come from the backend project's own trigger or results repository record: the repo is the last uri segment (its `repo_path` is `owner/name`), which must sit under the Gitea admin user (otherwise the command fails), and the secret is the record's. `--project` names the backend project (default `TEST_PROJECT_NAME`). The command fails with a clear message if the project is missing or does not have exactly one record of that kind.

`--entity` is `trigger` (default) or `results`. Steps that are the same for both repos (Gitea
repo, git secret, verify, Gitea token) take `--entity`; steps that differ in fields or
endpoints (the backend trigger repository vs results repository) are separate commands.

Each command reads only the env vars it uses,
all documented in `.dev.env.example`: the existing ones, plus `TEST_RESULTS_REPO`,
`TEST_RESULTS_REPO_URI`, `TEST_RESULTS_TARGET_DIR`, `GITEA_RESULTS_TOKEN_NAME` (must differ
from `GITEA_TOKEN_NAME`), `DEFAULT_PROJECT_DATASET` and `TEST_PR_IMAGE`.

The dataset defaults to a dummy stand-in. These env vars point it at a real database (all optional, defaults in brackets): `CLUSTER_DATASET_HOST` (`db-datasets.experiments.svc`), `DATASET_PORT` (`5432`), `DATASET_TYPE` (`postgres`), `DATASET_SCHEMA` (`cdm`, the read schema), `DATASET_SCHEMA_WRITE` (`results`), `DATASET_USERNAME` and `DATASET_PASSWORD` (`dummy`, stored in the dataset's secret). `experiments/experiments.sh seed` sets them for a real experiment.

## State and rules (for the end-to-end suites)

The suites in [tests/e2e](tests/e2e/README.md) use these to look at the test project and to change the state the webserver's rules act on.
Every write prints the HTTP status and body; `--expect STATUS` asserts the status (exit 1 if it differs), which is how the suites
check the 409 rules. `KIND` is `trigger`, `results`, `dataset` or `secret`; `--project NAME` picks another project.

| Command | What it does |
|---|---|
| `project-show [--project]` | JSON of the project's links (enabled, revoked, active), their pull requests (state, task), tasks and results. Read-only; stdout is clean JSON, so it pipes into `jq` |
| `project-set [--enabled true\|false] [--revoked true\|false] [--backfill]` | Enables or disables the project, or revokes or restores it (admin only) (`PATCH /projects/<id>`). A new project is disabled; enabling it skips the pull requests stored while it was off, unless `--backfill` (with `--enabled true`, on a disabled project) creates their triggers |
| `link-set KIND --enabled/--revoked true\|false` | Sets the flags of the project's link to a global resource. `--revoked` is admin only and immediate |
| `global-set KIND [--enabled true\|false] [--revoked true\|false]` | Turns the global resource behind the link on or off; `--revoked` (admin only, trigger and results) withdraws it from every project |
| `secret-set [--entity trigger\|results\|dataset] --enabled true\|false` | Turns a secret on or off. Off also disables the repositories and datasets that use it, and they stay off when it is turned on |
| `second-project-setup NAME` | Creates a second project linked to the same global resources (secrets, dataset, trigger and results repositories), enabled |
| `second-project-teardown NAME` | Deletes that project. The global resources stay |

## Demo

`fncli demo` walks through setting up everything needed to watch a Gitea repo, then proves it works: the two Gitea repos, the secrets, the project and its links, a merged pull request and its results. Before each step it says what the step creates, shows the equivalent fncli command and asks: Enter runs it, `s` skips it, `q` quits. Steps are separated by a line of dashes. After each step it lists the webserver calls it made (`METHOD /path -> status`, repeats counted) and shows what the step made: links to open in the browser (`Open:` lines) and the backend objects as JSON. A step that changes the project waits for the change to show in the project's state, polling every second, and prints it when it changes. A last, optional step tears the demo down (it asks again, default No).

```bash
cp .demo.env.example .demo.env   # once, in the repo root
fncli demo                       # step by step
fncli demo -y                    # every step without asking (no teardown)
fncli demo --from 8              # start at step 8, e.g. after a step failed
cp .demo-github.env.example .demo-github.env
fncli demo -y --env-file .demo-github.env   # the same on GitHub (phems-sandbox)
```

It needs the dev cluster with Tilt running and the Dagster sensors already running. The secrets, git provider, repository records and dataset are global (they belong to no project) and only the links to them belong to the project, while the Gitea repos live only in Gitea; each step says which it touches. The demo's own project, repos and dataset names are in `.demo.env`, which overrides `.dev.env`, so it never touches the e2e project; the steps are idempotent, so it can be rerun.

On GitHub (`TEST_GIT_PROVIDER=github`, see `.demo-github.env.example`) the repo must already exist and `GH_TOKEN` in `.dev.env` is stored as both repos' secret; fncli never creates or deletes GitHub repos or tokens. It uses the sensors' own client, `app/github.py`. `GIT_PROVIDER` is not the switch: `.dev.env` sets that for other tools.

## Real experiments

`experiments/experiments.sh seed NAME` loads an experiment's dummy data, then runs `fncli setup-project` with the experiment's own project, repos, tokens and `DATASET_*` values from `experiments/projects/NAME/project.env`. See [experiments/README.md](../../experiments/README.md).

## Maintenance

```bash
pipx list                          # see what pipx has installed
pipx reinstall phems                # after changing dependencies in pyproject.toml
pipx install --force --editable './dagster[cli]'   # from the repo root: a new command is missing, or "No module named 'fncli'"
```

The editable install points at the checkout it was run from. If you installed it from a worktree that was since removed (or you switch to another checkout), `fncli` fails with `No module named 'fncli'` or lacks the newer commands: run the last command again from the checkout you want.

fncli's dependencies are the `cli` extra in `dagster/pyproject.toml`; its Dagster code is
`dagster/app`, shared with the code location.

## Uninstall

Remove fncli:

```bash
pipx uninstall phems
```

That deletes its isolated environment and the `fncli` command. Your repo files are not
touched. To remove everything pipx has installed, use `pipx uninstall-all`.

To remove pipx itself, use the tool you installed it with:

```bash
sudo apt remove pipx                    # installed with apt
python3 -m pip uninstall pipx           # installed with pip
```

`pipx ensurepath` added a block to your shell config (look for a `# Created by pipx` comment
in `~/.bashrc`). Nothing else needs it once pipx is gone, so delete that block by hand if you
want it cleaned up. If you added the `export PATH="$HOME/.local/bin:$PATH"` line yourself,
remove that too, unless something else you use installs into `~/.local/bin`.

## Layout

```
dagster/fncli/
  cli.py            click group; loads .dev.env and registers commands
  cmds/             the commands, one module per entity (each has its init- and delete- commands; the init- ones create the global record, then assign it)
    common.py       env config classes and the Gitea and backend API builders
    actions.py      group commands: setup-/teardown-project, -backend, -gitea, and open-pr
    project.py      the backend project, and the find/init helpers the other entities use
    repository.py   Gitea repos and the backend trigger/results repository records
    secret.py       Gitea token and dataset secrets
    dataset.py      the backend dataset record
    pr.py           the individual PR steps
    sensor.py       start/stop/status of the Dagster sensors
    hello_world.py  install check
  backend.py        FncliBackendAPI: app.backend.BackendAPI plus the setup and teardown calls
  gitea.py          Gitea admin client on top of app.gitea
  k8s.py            host-side kubeconfig loading
  sensors.py        the Dagster GraphQL client
```

fncli imports the shared client code and models from `app` (`app.backend`, `app.gitea`,
`app.models`, ...). Anything only the CLI needs lives here, never in `dagster/app`.

## Simulation (several providers, repositories and projects)

`fncli simulate-setup`, `simulate-run`, `simulate-check` and `simulate-teardown` run a multi-provider simulation on the dev cluster
(`fncli/cmds/simulate.py`, logic in `fncli/simulation.py`). Four projects (`SimOne` to `SimFour`) link three trigger repositories and
two results repositories over two `GitProvider`s: the cluster's Gitea under its own name, and under an alias host `gitea-b` (a
Kubernetes ExternalName service the setup creates, so the providers' `uri` stay unique). One project watches repositories on both
providers, one repository is shared by two projects, and the projects deliver to different results repositories.
`simulate-run --seed N --prs-per-repo N` merges seeded pull requests (watched, invalid, unwatched and failing) in all trigger
repositories at once, waits for the sensors, then checks per project and repository: the right pull requests and tasks, no task shared
between projects, results delivered only to the project's own results repository. It writes a report to `artifacts/simulation/`.
It needs `GITEA_API_URI`, `NAMESPACE` and the usual backend settings in `.dev.env`, and has not been run. Later: an outage step (break
one provider's token or `api_uri`), then retries.
