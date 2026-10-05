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
pipx install --editable scripts/fncli
```

`--editable` links to the source, so changes to `scripts/fncli` take effect straight away.
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
fncli open-pr [--kind watched|unwatched|invalid] [--merge]
fncli teardown-project -y           # delete it all again

fncli setup-backend                 # or the two halves separately:
fncli setup-gitea [--project NAME]
fncli teardown-gitea -y [--project NAME]
fncli teardown-backend -y
```

- `setup-project`: builds the dev project. Side effects: creates two Gitea repos (trigger and results), a Gitea token for each (`fn-sensor`, `fn-results`), the K8s secrets holding them and the dataset's dummy credentials (via the backend), and the backend project, repository and dataset records.
- `open-pr`: opens a PR in the trigger repo for the sensor to find. Side effects: a new branch, one new file and a PR in Gitea; with `--merge` the PR is merged, which is what the sensor picks up.
- `teardown-project -y`: deletes the lot, side effects included: the backend records, the secrets (backend and K8s), the Gitea tokens and both Gitea repos with all their PRs. `-y` skips the prompt.

- `setup-backend`: the backend only, no Gitea call. Side effects: the backend project, the three secrets (K8s, holding placeholders: git secrets `{"TOKEN": "unset"}`, the dataset's dummy credentials) and the trigger repository (watching `main`), results repository and dataset records.
- `setup-gitea`: the Gitea side of an existing backend project, which is the reference (not the `TEST_*_REPO` env vars). Side effects: creates the Gitea repos its trigger and results repository records name, issues a Gitea token for each (`fn-sensor`, `fn-results`), writes it into that record's existing secret and checks Gitea accepts it.
- `teardown-gitea -y`: deletes the Gitea tokens and repos (with all their PRs) named by the project's backend records. The backend is left alone.
- `teardown-backend -y`: deletes the backend records, the secrets (backend and K8s) and the project. Gitea is left alone.

Intended use: `setup-backend` then `setup-gitea`, or `setup-project` for both in one go (and `teardown-gitea` then `teardown-backend`, or `teardown-project`).

A project is two Gitea repos (`--entity trigger` is the repo the sensor watches, `--entity
results` is where task results go), a dataset, and a secret for each of the three. Every
step is its own command and the group commands chain them; every step is idempotent and can be run
on its own or re-run after a failure. Deletes of something already gone are logged, not errors.

### Group commands (`cmds/actions.py`)

| Command | What it does |
|---|---|
| `setup-project` | Runs, in order: `init-backend-project`, `init-gitea-repo` (trigger, results), `init-git-secret` (trigger, results), `init-dataset-secret`, `init-backend-trigger-repo`, `init-backend-results-repo`, `init-backend-dataset`, `verify-git-secret` (trigger, results), `project-healthcheck` |
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
| `init-backend-project` | Finds or creates the test project in the backend, and enables it |
| `delete-backend-project` | Deletes the project with everything still under it (`DELETE /projects/<id>`) |
| `project-healthcheck` | Prints the backend's healthcheck for the test project as JSON (can the repos be reached with their tokens?). Exits 1 unless the status is `ok` |

**Repository** (`cmds/repository.py`)

| Command | What it does |
|---|---|
| `init-gitea-repo [--entity]` | Finds or creates the repo in Gitea |
| `delete-gitea-repo [--entity] [-y]` | Deletes the repo from Gitea, after asking. Backend records are left alone |
| `init-backend-trigger-repo [--base-branch]` | Registers the trigger repo with the backend so the sensor polls it. Without `--base-branch` the branch is the repo's default branch in Gitea (a Gitea call) |
| `init-backend-results-repo` | Registers the results repo as the project's results repository |
| `delete-backend-trigger-repo`, `delete-backend-results-repo` | Delete that record from the backend |

**Secret** (`cmds/secret.py`)

| Command | What it does |
|---|---|
| `init-git-secret [--entity]` | Stores a fresh Gitea token in the repo's K8s secret (`read:repository` for trigger, `write:repository` for results) |
| `init-backend-secret [--entity trigger\|results\|dataset]` | Creates the secret in the backend with placeholder values (`{"TOKEN": "unset"}`, or the dataset's dummies), with no Gitea call. An existing secret is left alone, so a real token is never overwritten |
| `init-dataset-secret` | Stores dummy `USERNAME` and `PASSWORD` in the dataset's secret (`<project>-dataset-creds`) |
| `verify-git-secret [--entity]` | Checks Gitea accepts the token currently stored in the repo's secret |
| `delete-secret [--entity trigger\|results\|dataset]` | Deletes the secret from the backend and K8s. Refused while a repo or dataset uses it |
| `delete-gitea-token [--entity]` | Deletes the Gitea token `init-git-secret` created for the repo |

**Dataset** (`cmds/dataset.py`)

| Command | What it does |
|---|---|
| `init-backend-dataset` | Registers the dummy dataset (needs the dataset secret) |
| `delete-backend-dataset` | Deletes the dataset record from the backend |

**Pull request** (`cmds/pr.py`; the file name, branch and title carry a timestamp, so it can be re-run)

| Command | What it does |
|---|---|
| `create-gitea-branch [--branch]` | Branches off the repo's default branch |
| `commit-gitea-file --branch [--kind]` | Commits one new file to the branch |
| `create-gitea-pr --branch [--kind]` | Opens the PR into the default branch |
| `merge-gitea-pr --number` | Merges the PR; the sensor only picks up merged PRs |

`--kind` picks the file, and so what the sensor makes of the PR: `watched` (default) is one
new `.json` spec file under the watch_dir, which becomes a task; `unwatched` is a file
outside the watch_dir, so the PR is ignored; `invalid` is a `.json` under the watch_dir
whose spec has an unknown field, so the PR is rejected.

`hello-world` prints a greeting, to check the CLI is installed.

The Gitea-facing steps (`init-gitea-repo`, `delete-gitea-repo`, `init-git-secret`, `verify-git-secret`, `delete-gitea-token`) also take `--from-backend` and `--project NAME`. By default the repo and its secret label come from the `TEST_*` env vars. With `--from-backend` they come from the backend project's own trigger or results repository record: the repo is the last uri segment, which must sit under the Gitea admin user (otherwise the command fails), and the secret is the record's. `--project` names the backend project (default `TEST_PROJECT_NAME`). The command fails with a clear message if the project is missing or does not have exactly one record of that kind.

`--entity` is `trigger` (default) or `results`. Steps that are the same for both repos (Gitea
repo, git secret, verify, Gitea token) take `--entity`; steps that differ in fields or
endpoints (the backend trigger repository vs results repository) are separate commands.

Each command reads only the env vars it uses,
all documented in `.dev.env.example`: the existing ones, plus `TEST_RESULTS_REPO`,
`TEST_RESULTS_REPO_URI`, `TEST_RESULTS_TARGET_DIR`, `GITEA_RESULTS_TOKEN_NAME` (must differ
from `GITEA_TOKEN_NAME`), `DEFAULT_PROJECT_DATASET` and `TEST_PR_IMAGE`.

`dev.db/backend_seed.py` is stale and destructive. It is not part of fncli: do not use it.

## Maintenance

```bash
pipx list                          # see what pipx has installed
pipx reinstall fncli               # after changing dependencies in pyproject.toml
```

pipx resolves dependencies from `pyproject.toml`, not `requirements.txt`. To refresh the
pinned, hashed `requirements.txt` after changing dependencies:

```bash
make pip_compile scripts/fncli
```

## Uninstall

Remove fncli:

```bash
pipx uninstall fncli
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
scripts/fncli/
  cli.py            click group; loads .dev.env and registers commands
  cmds/             the commands, one module per entity (each has its init- and delete- commands)
    common.py       env config classes and the Gitea and backend API builders
    actions.py      group commands: setup-/teardown-project, -backend, -gitea, and open-pr
    project.py      the backend project, and the find/init helpers the other entities use
    repository.py   Gitea repos and the backend trigger/results repository records
    secret.py       Gitea token and dataset secrets
    dataset.py      the backend dataset record
    pr.py           the individual PR steps
    hello_world.py  install check
  dagster/          copies of dagster/app client code (backend, gitea, k8s, models)
  pyproject.toml    package and dependency definition
  requirements.txt  pinned dependencies, generated by make pip_compile
```

`dagster/` holds copies of code from `dagster/app`, plus extensions used only by these
commands. It is imported as `fncli.dagster`, so it does not clash with the real `dagster`
package.
