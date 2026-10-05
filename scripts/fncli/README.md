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

Run commands from anywhere inside the repo: `.dev.env` is found by searching up from the current directory.

```bash
fncli --help              # list the commands
fncli setup-project       # set up a whole dev project
fncli open-pr --merge     # open a watched PR in Gitea and merge it
fncli teardown-project    # delete it all again
```

A project is two Gitea repos (`--role trigger` is the repo the sensor watches, `--role
results` is where task results go), a dataset, and a secret for each of the three. Every
step is its own command and the groups chain them; every step is idempotent and can be run
on its own or re-run after a failure.

**Setup**

| Command | What it does |
|---|---|
| `setup-project` | Renamed from `init-repo`. Runs, in order: `init-backend-project`, `init-gitea-repo` (trigger, results), `init-git-secret` (trigger, results), `init-dataset-secret`, `init-backend-trigger-repo`, `init-backend-results-repo`, `init-backend-dataset`, `verify-git-secret` (trigger, results), `project-healthcheck` |
| `init-gitea-repo [--role]` | Finds or creates the repo in Gitea |
| `init-backend-project` | Finds or creates the test project in the backend, and enables it |
| `init-git-secret [--role]` | Stores a fresh Gitea token in the repo's K8s secret (`read:repository` for trigger, `write:repository` for results) |
| `init-dataset-secret` | Stores dummy `USERNAME` and `PASSWORD` in the dataset's secret (`<project>-dataset-creds`) |
| `verify-git-secret [--role]` | Checks Gitea accepts the token currently stored in the repo's secret |
| `init-backend-trigger-repo` | Registers the trigger repo with the backend so the sensor polls it |
| `init-backend-results-repo` | Registers the results repo as the project's results repository |
| `init-backend-dataset` | Registers the dummy dataset (needs the dataset secret, and Keycloak working) |
| `project-healthcheck` | Prints the backend's healthcheck for the test project as JSON (can the repos be reached with their tokens?). Exits 1 unless the status is `ok` |

**Open a PR** in the trigger repo (the file name, branch and title carry a timestamp, so it can be re-run)

| Command | What it does |
|---|---|
| `open-pr [--kind] [--merge]` | Runs `create-gitea-branch`, `commit-gitea-file`, `create-gitea-pr`, and with `--merge` `merge-gitea-pr` |
| `create-gitea-branch [--branch]` | Branches off the repo's default branch |
| `commit-gitea-file --branch [--kind]` | Commits one new file to the branch |
| `create-gitea-pr --branch [--kind]` | Opens the PR into the default branch |
| `merge-gitea-pr --number` | Merges the PR; the sensor only picks up merged PRs |

`--kind` picks the file, and so what the sensor makes of the PR: `watched` (default) is one
new `.json` spec file under the watch_dir, which becomes a task; `unwatched` is a file
outside the watch_dir, so the PR is ignored; `invalid` is a `.json` under the watch_dir
whose spec has an unknown field, so the PR is rejected.

**Teardown**

| Command | What it does |
|---|---|
| `teardown-project [-y]` | After asking (`-y` / `--yes` skips the prompt), runs: `delete-backend-dataset`, `delete-backend-results-repo`, `delete-backend-trigger-repo`, `delete-secret` (trigger, results, dataset), `delete-backend-project`, `delete-gitea-repo` (trigger, results). Both Gitea repos are always deleted |
| `delete-backend-dataset`, `delete-backend-results-repo`, `delete-backend-trigger-repo`, `delete-backend-project` | Delete that record; the project goes with everything still under it (`DELETE /projects/<id>`) |
| `delete-secret [--role trigger\|results\|dataset]` | Deletes the secret from the backend and K8s. Refused while a repo or dataset uses it |
| `delete-gitea-repo [--role] [-y]` | Deletes the repo from Gitea, after asking. Backend records are left alone |

Deletes of something already gone are logged, not errors.

`hello-world` prints a greeting, to check the CLI is installed.

`--role` is `trigger` (default) or `results`. Each command reads only the env vars it uses,
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
    common.py       config classes, API builders and helpers shared by the modules
    project.py      project commands, plus setup-project and teardown-project
    repository.py   Gitea repos and the backend trigger/results repository records
    secret.py       Gitea token and dataset secrets
    dataset.py      the backend dataset record
    pr.py           open-pr and its steps
    hello_world.py  install check
  dagster/          copies of dagster/app client code (backend, gitea, k8s, models)
  pyproject.toml    package and dependency definition
  requirements.txt  pinned dependencies, generated by make pip_compile
```

`dagster/` holds copies of code from `dagster/app`, plus extensions used only by these
commands. It is imported as `fncli.dagster`, so it does not clash with the real `dagster`
package.
