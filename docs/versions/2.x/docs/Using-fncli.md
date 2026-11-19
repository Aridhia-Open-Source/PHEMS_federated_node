# Using fncli

`fncli` is the command-line tool of the Federated Node repository. It sets a development node up from a few YAML files, asks the node to run a task, and checks what happened. This page explains the files and the commands.

**It is a development and demo tool.** Its setup commands assume the local development cluster, with Gitea as the git host and Tilt's port-forwards. On a real node, set the git provider, repositories and secrets up with the API ([Set up a project](./Set-Up-A-Project)). Using `fncli apply` or `delete` on a node you care about needs a decision of its own, and `delete --all` must never be run against one.

To install it and run the demo from nothing, see [Run locally](./Run-Locally).


## Install

From the repo root, with [mise](https://mise.jdx.dev/) installed.

```sh
mise run setup
fncli hello-world        # prints "Hello, world!"
```

`mise run setup` installs fncli, editable, into `.venv` at the repo root. With [mise activated in your shell](https://mise.jdx.dev/getting-started.html#activate-mise), `fncli` is on your `PATH` anywhere in the repo. The install belongs to that checkout, so a worktree needs its own `mise run setup`. If `fncli` fails with `No module named 'fncli'`, or lacks a command, run `mise run setup` again from the checkout you want. If you installed fncli with pipx before, remove that copy: `pipx uninstall phems`.

`fncli --help` lists the commands. fncli reads cluster secrets from the **current kubectl context**, so check `kubectl config current-context` is the cluster you mean.


## The files

Three kinds of file drive fncli. **None holds a secret value**, so they are safe to commit.

| Path | What it holds | Committed |
|---|---|---|
| `bootstrap/context.yaml` | Which node fncli works on, and the defaults of its commands | No: gitignored. `bootstrap/examples/context.yaml` is the example |
| `bootstrap/globals*.yaml` | The global resources: git providers, secrets, repositories | Yes |
| `bootstrap/projects/<name>.yaml` | One project, and what it is assigned | Yes |
| `triggers/*.json` | A trigger file: the task spec a pull request adds | Yes |
| `experiments/<name>/dataset.yaml` | An experiment's dataset and its secret | Yes |

The files are split by who writes them and when. The node is chosen apart from the content, so the same globals and project files serve the demo, the end-to-end tests and your own node.

### The context file

```yaml
node:
  url: http://localhost:5000          # nexus-api (the Tilt port-forward)
  kube_context: kind-fn               # fncli refuses to run when kubectl points elsewhere
  keycloak_namespace: keycloak        # where fncli's login is read from
  env_file: .dev.env                  # GH_APP_ID and friends; found from here up
defaults:
  project: demo-gitea                 # for fncli trigger and fncli demo without --project
  trigger_type: pr                    # pr, or api (not built yet)
```

- Every command that talks to the node reads it. fncli looks for `bootstrap/context.yaml` from the current directory up, so it works from any folder of the repo. `--context FILE` or `FNCLI_CONTEXT` names another.
- Every command **refuses to run when kubectl's current context differs from `node.kube_context`**. The context file is the one authority for the target.
- `FNCLI_DEFAULT_PROJECT` and `FNCLI_DEFAULT_TRIGGER_TYPE` in the shell win over `defaults:`, and a flag wins over both. A command that uses a default says so on its first line.

### Node files

A node file lists any of the providers, secrets, repositories, datasets and projects of a node. The global resources go in one file and a project in another. A project file is only its name and what it is assigned, **by name**:

```yaml
# bootstrap/examples/projects/demo-gitea.yaml
version: 1
projects:
  - name: demo-gitea
    datasets: [demo-db]                  # on the node already
    repositories:
      triggers:
        - repository: http://gitea.fn.svc:4000/gitea_admin/demo-trigger-repo
          watch_dir: specs/
          base_branch: main
      results:
        repository: http://gitea.fn.svc:4000/gitea_admin/demo-results-repo
        target_dir: results/
        base_branch: main
```

- **The keys are the backend's own unique fields**, so a file holds no ids: provider uri, repository uri, secret label, dataset name, project name.
- **Where a value comes from.** A secret's values say where fncli reads them at apply time: `env`, `file`, `k8s_secret`, `gitea_oauth` (fncli makes and authorises an OAuth app in Gitea) or `generate` (a random value, for stand-in credentials only). A bare string where a reference is expected is rejected, so a file can never hold a secret.
- **References across files resolve against the node.** A project may name a repository, dataset or secret that is in another file, as long as it is on the node when `diff` reads it. One that is in neither blocks the row that names it ("not in the file or on the node"), and `apply` leaves that row alone.
- `-f` takes a path, or one relative to the nearest `bootstrap/` directory, so `-f examples/globals-gitea.yaml` works from anywhere in the repo.
- Names may use only lowercase letters, digits, `-` and `.`, because they become secret labels.

### Trigger files

A trigger file is the JSON that asks the node to run a task: `{"spec": {"image": "...", "env": {...}}}`. It is the same task spec a researcher adds in a pull request ([Researcher guide](./Researcher-Guide)). A path, or one relative to `triggers/`, works. The repo has `triggers/examples/demo.json`, and `demo-failing.json`, whose task fails on purpose.


## diff, apply, delete

These work in the style of kubectl.

| Command | What it does |
|---|---|
| `fncli diff -f FILE` | Prints one row per entity: `+` create, `~` change, `=` unchanged, `!` needs a confirmation, `x` blocked. Changes nothing. A secret to be created lists where each value is read from and whether it can be |
| `fncli apply -f FILE [-y] [--rotate LABEL]` | Prints that plan, asks, then does it in dependency order: secrets, providers, Gitea repositories (if the file has a `gitea:` section), repositories, datasets, projects. A project is created disabled and enabled last |
| `fncli delete -f FILE [--all] [-y]` | Deletes the file's projects. With `--all`, also its repositories, datasets, secrets (with their stored values) and providers |

How they behave:

- **Apply is additive.** It creates and updates, and never deletes. Taking an entry out of a file changes nothing on the node.
- **Apply is repeatable.** A second apply of an unchanged file changes nothing, and a failed one can be run again. It stops at the first backend error and says what was done and what was not.
- **Secrets are create-only.** An existing secret is left alone. `--rotate LABEL` rewrites all its keys, and authorises a Gitea OAuth app again. A secret edited elsewhere is not noticed until `--rotate`.
- **Changes only touch what differs.** An assignment that exists is changed with a `PATCH` of the fields that differ, so a repeated apply does not re-enable what you switched off.
- **Disruptive changes are marked.** A dataset's host, port, type or schemas, and a results repository's `target_dir` or `base_branch`, are pinned into each task when it is created, so changing them fails earlier tasks. Assigning a results repository to a live project needs the project disabled, so apply asks first.
- **Delete is a soft delete** through the API's `DELETE` routes, never with `?force=true`. It works in reverse order: what uses a thing goes before the thing. What another project outside the file still uses is **skipped**, with the backend's reason, and delete exits 1. A provider that other repositories are on is kept.
- **Gitea repositories and OAuth apps are left in place**, and fncli never creates or deletes GitHub repositories, tokens or Apps.
- Applying a file again after `delete` recreates everything cleanly: a deleted name is free again. When projects share globals, delete the second project's file first, then the first with `--all`.


## Trigger a task

```sh
fncli trigger --pr --merge --watch examples/demo.json
```

`fncli trigger FILE` asks the node to run a task with a trigger file. With `--pr` it adds the file on a new branch, under the watch directory of the project's trigger repository, and opens a pull request (taken from the project's record in the node, not from any env). With `--merge` it merges the pull request, which is what the sensors pick up, and with `--watch` it follows the pull request, its task and its run, and exits 1 on a rejection or a failed run.

The project and the way default to the context's `defaults`. `--api` is reserved for sending the same file to the task API, and says it is not built yet. On GitHub, the pull requests into the trigger repository are the researcher's work, so they use `RESEARCHER_GIT_TOKEN`, or the token of `gh auth login`. On Gitea they use the admin login.


## demo

`fncli demo -f PROJECT_FILE [TRIGGER]` shows the pull request process on a node that `apply` has already set up. It **creates and deletes nothing**.

1. It builds the plan `diff` prints for the project file. If anything would change, it stops with exit 1 and lists the rows. Nothing is applied for you.
2. Then it checks the dataset and the git host, walks a pull request into the trigger repository, the task it becomes and the results pull request, then checks the whole project. Before each step it says what the step does, shows the equivalent fncli command, and asks.

The flow is `apply` the globals, `apply` the project, `demo` as often as you like, then `delete`. [Run locally](./Run-Locally#7-the-gitea-demo) walks it.


## Sensors and checks

These act on the project in your context's defaults (or `--project NAME`), and talk only to nexus-api and Dagster. They are written for the development cluster.

| Command | What it does |
|---|---|
| `start-sensor` / `stop-sensor` (`--group G` or `--name N`) | Starts or stops Dagster sensors. Groups: `ingest`, `evaluate`, `launcher`, `status`, `delivery`, `all`. A group stops in reverse order |
| `sensor-status` | Every sensor's status and last three ticks |
| `project-show` | JSON of the project's resources, pull requests, tasks and results |
| `project-set --enabled/--revoked true\|false [--backfill]` | Enables, disables, revokes or restores a project |
| `resource-set KIND ...`, `global-set KIND ...`, `secret-set ...` | The flags on a project's use of a resource, on the resource itself, and on a secret |
| `project-healthcheck`, `verify-project` | The project's healthcheck, and a read-only report on it. Exit 1 on a failure |
| `verify-git-secret [--entity trigger\|results]` | Asks nexus-api for a git token for the repository and checks the git host accepts it |
| `merge-results-pr --number N` | Merges a results pull request, so the sync sensor records it as merged |

`KIND` is `trigger`, `results`, `dataset` or `secret`. The `--revoked` options also need the `keycloak-first-user` secret that `mise run deploy` creates, so on a real node revoke through the API instead.


## Experiments

`fncli experiment` runs a real experiment image against the development node: see [Experiments](./Experiments).


## More detail

The repo's [fncli README](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/dagster/fncli/README.md) has every command and option. The design is in the decision records [0025](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0025-fncli-bootstrap-files-diff-apply-delete.md) to [0030](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0030-fncli-demo-only-walks-the-pull-request-process.md).
