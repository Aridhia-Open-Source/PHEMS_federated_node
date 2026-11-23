# Using fncli

`fncli` is the command-line tool of the Federated Node repository. It makes the Gitea repositories and credentials a development node needs, asks the node to run a task, and checks what happened. The node's own configuration is Kubernetes resources that you apply with `kubectl`. This page explains the files and the commands.

**It is a development and demo tool.** Its setup commands assume the local development cluster, with Gitea as the git host and Tilt's port-forwards. On a real node, set the git provider, repositories and secrets up with the API ([Set up a project](./Set-Up-A-Project)) or the chart values. Using `kubectl apply` or `delete` of the dev files in `config/` on a node you care about needs a decision of its own.

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

Three kinds of file drive the dev setup. **None holds a secret value**, so they are safe to commit.

| Path | What it holds | Committed |
|---|---|---|
| `bootstrap/context.yaml` | Which node fncli works on, and the defaults of its commands | No: gitignored. `bootstrap/examples/context.yaml` is the example |
| `config/*.yaml`, `config/*/*.yaml` | The node config: git providers, secrets, repositories, datasets and projects, as Kubernetes resources (`kubectl apply -f`) | Yes |
| `triggers/*.json` | A trigger file: the task spec a pull request adds | Yes |
| `experiments/<name>/values.yaml` | An experiment's database, and (rendered by the chart) its dataset and its secret | Yes |

The files are split by who writes them and when. The node fncli talks to is chosen apart from the node config, so the same files serve the demo, the end-to-end tests and your own node.

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

### Node config

The node's providers, secrets, repositories, datasets and projects are Kubernetes custom resources (group `fn.aridhia.com/v1alpha1`: GitProvider, NodeSecret, Repository, Dataset, Project) in `config/`. You apply them with `kubectl`, and the nexus operator syncs them to nexus-api. A project names what it is assigned, **by name**:

```yaml
# config/demo.yaml (the project)
apiVersion: fn.aridhia.com/v1alpha1
kind: Project
metadata:
  name: demo-gitea
  namespace: fn-operator
spec:
  datasets: [demo-db]                  # the experiments chart's
  repositories:
    triggers:
      - repository: http://gitea.fn.svc:4000/gitea_admin/demo-trigger-repo
        watchDir: specs/
        baseBranch: main
    results:
      repository: http://gitea.fn.svc:4000/gitea_admin/demo-results-repo
      targetDir: results/
      baseBranch: main
```

- **The keys are the backend's own unique fields**, so a file holds no ids: provider uri, repository uri, secret name, dataset name, project name.
- **A secret's values come from a Kubernetes Secret.** A NodeSecret names it (`fromSecret`) or points at keys of other Secrets, so a file can never hold a secret value. `fncli gitea setup` makes the Secret for a Gitea repository; for a GitHub App you run `kubectl create secret` ([Run locally](./Run-Locally)).
- **The operator reports in each resource's status.** `kubectl get fn -n fn-operator` shows Synced and a Message, for example a Secret or dataset that is not there yet.
- Names may use only lowercase letters, digits, `-` and `.`.

The format, the operator and more examples are in [ADR 0032](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0032-declarative-node-config-through-an-operator.md).

### Trigger files

A trigger file is the JSON that asks the node to run a task: `{"spec": {"image": "...", "env": {...}}}`. It is the same task spec a researcher adds in a pull request ([Researcher guide](./Researcher-Guide)). A path, or one relative to `triggers/`, works. The repo has `triggers/examples/demo.json`, and `demo-failing.json`, whose task fails on purpose.


## kubectl apply, delete and gitea setup

The node config is applied in the style of kubectl, because it is kubectl.

| Command | What it does |
|---|---|
| `fncli gitea setup -f FILE [--rotate NODESECRET]` | Creates the Gitea repositories of the file's Repository resources and, for each NodeSecret they name, a Gitea OAuth app named after it. Writes `CLIENT_ID`, `CLIENT_SECRET` and `REFRESH_TOKEN` into the Kubernetes Secret the NodeSecret's `fromSecret` names |
| `kubectl apply -f config/` | The operator syncs each resource to nexus-api, in dependency order. A project is created disabled and enabled last |
| `kubectl get fn -n fn-operator` | Each resource's Synced and Message |
| `kubectl diff -f FILE` | What an apply would change |
| `kubectl delete -f FILE` | Soft-deletes the resources' records |

How they behave:

- **Run `fncli gitea setup` first.** A NodeSecret whose Secret does not exist yet stays unsynced until it does.
- **Secrets are create-only.** A Secret that exists is kept. `--rotate NODESECRET` writes it again, and authorizes the Gitea OAuth app again.
- **Apply is repeatable.** The operator creates what is missing and changes only what differs, so a second apply of an unchanged file changes nothing.
- **Disruptive changes are marked.** A dataset's host, port, type or schemas, and a results repository's `targetDir` or `baseBranch`, are pinned into each task when it is created, so changing them fails earlier tasks.
- **Delete is a soft delete** through the API's `DELETE` routes, never with `?force=true`. What another project outside the file still uses is kept: the resource stays `Terminating`, with the backend's reason in its Message, until that project is deleted. A provider that other repositories are on is kept.
- **Gitea repositories, OAuth apps and Kubernetes Secrets are left in place**, and fncli never creates or deletes GitHub repositories, tokens or Apps.
- Applying a file again after `kubectl delete` recreates everything cleanly: a deleted name is free again. When projects share resources, delete the second project's file first, then the first.


## Trigger a task

```sh
fncli trigger --pr --merge --watch examples/demo.json
```

`fncli trigger FILE` asks the node to run a task with a trigger file. With `--pr` it adds the file on a new branch, under the watch directory of the project's trigger repository, and opens a pull request (taken from the project's record in the node, not from any env). With `--merge` it merges the pull request, which is what the sensors pick up, and with `--watch` it follows the pull request, its task and its run, and exits 1 on a rejection or a failed run.

The project and the way default to the context's `defaults`. `--api` is reserved for sending the same file to the task API, and says it is not built yet. On GitHub, the pull requests into the trigger repository are the researcher's work, so they use `RESEARCHER_GIT_TOKEN`, or the token of `gh auth login`. On Gitea they use the admin login.


## demo

`fncli demo [TRIGGER] [--project NAME]` shows the pull request process on a node where `kubectl apply` has already set up the project. It **creates and deletes nothing**.

1. It reads the project's Project resource. If the operator has not synced it, it stops with exit 1 and shows the operator's message. Nothing is applied for you.
2. Then it checks the dataset and the git host, walks a pull request into the trigger repository, the task it becomes and the results pull request, then checks the whole project. Before each step it says what the step does, shows the equivalent fncli command, and asks.

The flow is `fncli gitea setup -f config/gitea.yaml -f config/demo.yaml`, `kubectl apply -f config/`, `demo` as often as you like, then `kubectl delete -f config/demo.yaml`. [Run locally](./Run-Locally#7-the-gitea-demo) walks it.


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

`KIND` is `trigger`, `results`, `dataset` or `secret`. The `--revoked` options need an Administrator login (`FN_USERNAME`).


## Experiments

`fncli experiment` runs a real experiment image against the development node: see [Experiments](./Experiments).


## More detail

The repo's [fncli README](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/dagster/fncli/README.md) has every command and option. The design is in the decision records [0032](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0032-declarative-node-config-through-an-operator.md) (node config as Kubernetes resources) and, for history, [0025](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0025-fncli-bootstrap-files-diff-apply-delete.md) to [0030](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0030-fncli-demo-only-walks-the-pull-request-process.md).
