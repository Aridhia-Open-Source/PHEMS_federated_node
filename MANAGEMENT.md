# Managing a Federated Node

An admin's guide to setting up what a node needs before it runs anything: the global resources (secrets, a git provider, repositories, datasets) and a project that uses them. Install the node first ([DEPLOYMENT.md](DEPLOYMENT.md)).

There are two ways to do it:

- **The API.** Works on any node, and is the way to set up a real one. [Set up with the API](#set-up-with-the-api).
- **`fncli`.** A command-line tool that does the same calls for you on the **development cluster**, with Gitea as the git host. [Using fncli](#using-fncli).

Both create the same records, so you can mix them.

- [How it fits together](#how-it-fits-together)
- [Before you start](#before-you-start)
- [Set up with the API](#set-up-with-the-api)
- [Start the sensors](#start-the-sensors)
- [Run the first task](#run-the-first-task)
- [Using fncli](#using-fncli)
- [Switch things on and off](#switch-things-on-and-off)
- [Add another project](#add-another-project)
- [Checking on it](#checking-on-it)

## How it fits together

Secrets, datasets, git providers, and trigger and results repositories are **global**: they belong to no project and are created once, by an admin. A **project** is then assigned the ones it uses. Each assignment is a **project resource**, and it holds what is per project (which directory to watch, where results go, the enabled and revoked flags). The design is in [ADR 0006](project/decisions/0006-global-resources-and-project-resources.md); the end-to-end flow is in [docs/architecture/flows.md](docs/architecture/flows.md).

Create them in this order, because each one refers to the one before:

| # | What | Needs | Holds |
|---|---|---|---|
| 1 | Secret (three of them) | nothing | A git token for each repository, and the dataset's database login. Stored in Kubernetes; the API never returns the values |
| 2 | Git provider | nothing | The git host: GitHub or Gitea, with its web and API addresses |
| 3 | Trigger repository | provider, secret | The repository whose merged pull requests become tasks |
| 4 | Results repository | provider, secret | The repository results are pushed to, as a branch and a pull request |
| 5 | Dataset | secret | A database the tasks read, and where they may write |
| 6 | Project | nothing | The unit of work. Created **disabled** |
| 7 | Project resources | project and 3, 4, 5 | The trigger repository (`watch_dir`, `base_branch`), the results repository (`target_dir`), the dataset |
| 8 | Enable the project, start the sensors | 7 | Nothing runs before this |

How a task starts: a pull request merged into the trigger repository's base branch, adding a `.json` spec file under `watch_dir`. The sensors poll for it, the backend stores it once and gives each project that watches it a trigger, Dagster launches the task pod, and the results come back as a pull request in the results repository.

## Before you start

You need the admin login (the first user from the install) and the node's address.

```bash
FN=https://fn.your-institution.example.com   # http://localhost:5000 on the dev cluster

TOKEN=$(curl -sS -X POST "$FN/login" \
  -F "username=admin@your-institution.example.com" \
  -F "password=<the first user's password>" | jq -r .token)
```

`/login` takes form fields, not JSON. The token is a bearer token and lasts 8 hours (`token.life`); `POST /refresh_token` renews it. Every call below sends it:

```bash
AUTH=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")
```

Creating global resources and revoking things is **admin only**.

## Set up with the API

The examples use GitHub. Replace the names. Each `POST` returns the new record, and the commands keep its `id` for the next step. They were written from the backend's request models and have not been run against a live node.

### 1. Secrets

Make three, one per thing that needs a credential. A label is the name you use for it in later calls. It also becomes part of a Kubernetes name, so use lowercase letters, digits, `-` and `.`.

```bash
# Trigger repository: a token that can read the repository and its pull requests
curl -sS -X POST "$FN/global/secrets" "${AUTH[@]}" -d '{
  "label": "demo-trigger-creds", "provider": "K8S",
  "values": {"TOKEN": "<github token with read access>"}
}' | jq

# Results repository: a token that can push a branch and open a pull request
curl -sS -X POST "$FN/global/secrets" "${AUTH[@]}" -d '{
  "label": "demo-results-creds", "provider": "K8S",
  "values": {"TOKEN": "<github token with write access>"}
}' | jq

# Dataset: the database login. The keys are USERNAME and PASSWORD
curl -sS -X POST "$FN/global/secrets" "${AUTH[@]}" -d '{
  "label": "demo-dataset-creds", "provider": "K8S",
  "values": {"USERNAME": "<db user>", "PASSWORD": "<db password>"}
}' | jq
```

- Git tokens are stored under the key `TOKEN`.
- Use a separate token for each repository, scoped to just that repository. The trigger token only reads. The results token writes (contents and pull requests).
- To rotate a value later: `PATCH $FN/global/secrets/<label>` with `{"values": {...}}`. A rotation reaches work already running.

### 2. Git provider

One per git host. Repositories on the same host share it.

```bash
PROVIDER_ID=$(curl -sS -X POST "$FN/global/providers" "${AUTH[@]}" -d '{
  "name": "github", "type": "github",
  "uri": "https://github.com", "api_uri": "https://api.github.com"
}' | jq -r .id)
```

`type` is `github` or `gitea`. `uri` is the host's web address and `api_uri` its API base URL, which the tokens are sent to (for Gitea: `https://<host>/api/v1`).

### 3. Trigger and results repositories

`repo_path` is `owner/name`. `secret_label` is the secret from step 1.

```bash
TRIGGER_ID=$(curl -sS -X POST "$FN/global/repositories/triggers" "${AUTH[@]}" -d "{
  \"provider_id\": $PROVIDER_ID,
  \"repo_path\": \"your-org/fn-triggers\",
  \"secret_label\": \"demo-trigger-creds\"
}" | jq -r .id)

RESULTS_ID=$(curl -sS -X POST "$FN/global/repositories/results" "${AUTH[@]}" -d "{
  \"provider_id\": $PROVIDER_ID,
  \"repo_path\": \"your-org/fn-results\",
  \"secret_label\": \"demo-results-creds\"
}" | jq -r .id)
```

The repositories have to exist already; the FN does not create them.

### 4. Dataset

```bash
DATASET_ID=$(curl -sS -X POST "$FN/global/datasets" "${AUTH[@]}" -d '{
  "name": "study_omop",
  "host": "<dataset database host>",
  "port": 5432,
  "type": "postgres",
  "secret_label": "demo-dataset-creds",
  "read_schema": "cdm",
  "write_schema": "results"
}' | jq -r .id)
```

- `name` is the **database name** on that host (stored lowercase), not a display label. Dataset names are unique across the node.
- `type` is `postgres` (the default), `mssql`, `mysql`, `mariadb` or `oracle`.
- `read_schema` is what tasks read. `write_schema` is where they write results, and it must already exist with write rights for the dataset user.
- `extra_connection_args` is optional and appended to the connection string (for example `sslmode=require`).
- **Unknown keys on a dataset are ignored**, so a misspelled field still returns 201 with that value unset. Read it back:

  ```bash
  curl -sS "$FN/global/datasets/$DATASET_ID" "${AUTH[@]}" | jq
  ```

Check that the dataset is reachable now, instead of when the first task fails: `GET /global/datasets/$DATASET_ID/healthcheck`.

### 5. Project

A new project is **disabled**. That is deliberate: the results repository can only be assigned while the project is disabled.

```bash
PROJECT_ID=$(curl -sS -X POST "$FN/projects" "${AUTH[@]}" -d '{
  "name": "example", "description": "First project", "enabled": false
}' | jq -r .id)
```

### 6. Assign the resources to the project

`PUT` assigns. The id in the URL is the **global resource's id**, not the project resource's. A repeat `PUT` replaces the project's settings for that resource.

```bash
# Dataset. The first dataset assigned becomes the project's default
curl -sS -X PUT "$FN/projects/$PROJECT_ID/datasets/$DATASET_ID" "${AUTH[@]}" -d '{}' | jq

# Trigger repository: the directory to watch, and the branch merges are tracked on
curl -sS -X PUT "$FN/projects/$PROJECT_ID/repositories/triggers/$TRIGGER_ID" "${AUTH[@]}" -d '{
  "watch_dir": "specs/", "base_branch": "main"
}' | jq

# Results repository: the directory results go under, and the branch results pull requests start from and go into. A project has one
curl -sS -X PUT "$FN/projects/$PROJECT_ID/repositories/results/$RESULTS_ID" "${AUTH[@]}" -d '{
  "target_dir": "results/", "base_branch": "main"
}' | jq
```

- `base_branch` is required for both repositories: it is never guessed from the repository's default branch.
- `watch_dir` must not be empty: only a pull request that adds a `.json` file under it becomes a task.
- The trigger resource's cursor is set when you assign it, and pull requests merged before it are not run (there is no backfill unless you ask for one when enabling the project).

### 7. Check, then enable

```bash
curl -sS "$FN/projects/$PROJECT_ID/healthcheck" "${AUTH[@]}" | jq      # can every resource be reached with its token?
curl -sS "$FN/global/healthcheck" "${AUTH[@]}" | jq                     # the whole node
```

A failing check (a wrong token, an unreachable database or git host) shows in the body with status 200, never a 500, and never contains a secret value. Fix what it names, then:

```bash
curl -sS -X PATCH "$FN/projects/$PROJECT_ID" "${AUTH[@]}" -d '{"enabled": true}' | jq
```

Enabling skips pull requests stored while the project was off. To have them run, send `{"enabled": true, "backfill": true}` instead.

## Start the sensors

Every Dagster sensor starts **stopped**, so nothing is polled and no task runs until you start them. Do it once the project is enabled. Order does not matter.

With the Dagster UI (it has no login, so reach it by port-forward and never publish it):

```bash
kubectl port-forward -n federated-node svc/federatednode-dagster-webserver 3000:80
```

Open http://localhost:3000, go to **Automation**, and turn on all twelve sensors. With `fncli`: `fncli start-sensor --group all` (see below).

The sensors, by group (`fncli` uses the group names):

| Group | Sensors | Job |
|---|---|---|
| `ingest` | `git_pull_request_ingest_sensor` | Polls each trigger repository once and stores new merged pull requests |
| `evaluate` | `git_pull_request_evaluate_sensor` | Turns each stored pull request into a task, or rejects it with a cause |
| `launcher` | `task_launcher_sensor` | Starts a Dagster run for each pending task |
| `status` | five run-status sensors, `task_reconcile_sensor` | Copy the run's status onto the task |
| `delivery` | `task_results_delivery_sensor`, `results_pull_request_sync_sensor`, `results_delivery_retry_sensor` | Push results, track the results pull request, retry failures |

How often they tick (`fnDagster.sensors.minIntervalSeconds`, default 30 s) and how long a failed run waits before a retry (`retryIntervalSeconds`, default 60 s) are chart values. Why they start stopped and why order does not matter: [ADR 0014](project/decisions/0014-dagster-pipeline-ops-sensors-and-retries.md).

## Run the first task

1. In the trigger repository, on a branch, add a spec file under `watch_dir`, for example `specs/first-task.json`:

   ```json
   {
     "spec": {
       "image": "ghcr.io/your-org/your-analytics-image:1.0",
       "dataset": "my-dataset",
       "env": {"MY_VAR": "value"},
       "tags": {"team": "analytics"},
       "config": {"epochs": 3},
       "compute": {"requests": {"cpu": "500m", "memory": "1Gi"}, "limits": {"cpu": "2", "memory": "4Gi"}}
     },
     "metadata": {"ticket": "ABC-1"}
   }
   ```

   Only `spec` and `metadata` are allowed at the top level, and `spec` is required. In `spec`, `image` is required; `dataset`, `env`, `tags`, `config` and `compute` are optional. Any other field, in either place, makes the pull request `REJECTED`.
   - `env` keys can't be `ARTIFACT_PATH`, `CDM_SCHEMA`, `WRITE_SCHEMA`, `DB_USERNAME`, `DB_PASSWORD`, `CONNECTION_STRING` or `CONFIG_PATH`, or start with `DAGSTER_` or `KUBERNETES_`, in any letter case: the run sets those itself.
   - `tags` are text to text, copied onto the task's run. A key is 1 to 63 letters, digits, `_`, `.` or `-` (so no `/`), otherwise the pull request is rejected.
   - `config` is a JSON object the task reads as a file. Its contents are not checked.
   - `compute` asks for CPU and memory: `requests` and `limits`, each with an optional `cpu` and `memory` (`500m`, `2`, `512Mi`, `4Gi`). A limit can't be lower than its request, nothing can be over the node max, and a request without a limit of its own can't be over the default limit. Without it the task namespace's defaults apply. The max and the defaults are the chart's `taskCompute` values (`taskCompute.max` and `taskCompute.default`).
   - `metadata` is yours: any JSON, not checked, kept with the task.
   - The task is named `<project name>:PR#<pull request number>`.

   The rules are in [ADR 0002](project/decisions/0002-task-spec-and-derivation.md).
2. Open a pull request into the base branch and **merge it**. Only merged pull requests are read.
3. Wait a few sensor intervals, then look:

   ```bash
   curl -sS "$FN/projects/$PROJECT_ID/tasks" "${AUTH[@]}" | jq
   ```

   The task goes pending, queued, running, then success. The Dagster UI shows the run and its logs under **Runs**.
4. A pull request appears in the results repository, with `results.zip`, `spec.json` (the pull request's spec file, as merged) and `run.json` (node, project, trigger, task and delivery details) on a branch under `target_dir`. Merge it to close the loop: the sync sensor then records the result as merged.

## Using fncli

`fncli` makes the setup above a few commands on the development cluster: it creates two Gitea repositories and a token for each, the secrets, the git provider, both repositories, a dataset, a project, and the project resources, then enables the project. It is a dev and ops tool, not a product interface ([ADR 0018](project/decisions/0018-fncli-dev-ops-tool.md)). Its setup commands assume the dev cluster: Gitea as the git host, Tilt's port-forwards, and dummy dataset credentials unless you set `DATASET_*`.

### Install

From the repo root. You need [mise](https://mise.jdx.dev/), activated in your shell.

```bash
mise run setup
fncli hello-world        # prints "Hello, world!"
```

`mise run setup` installs fncli, editable, into `.venv` at the repo root. If you installed it with pipx before, run `pipx uninstall phems`. The full install notes, troubleshooting and uninstall are in [dagster/fncli/README.md](dagster/fncli/README.md).

### What it needs

- The dev cluster running with Tilt up (`mise run deploy`, then `tilt up`: [DEPLOYMENT.md](DEPLOYMENT.md#run-it-locally)). That gives the port-forwards: nexus-api `localhost:5000`, Dagster `localhost:3000`, Gitea `localhost:4000`.
- `kubectl` pointing at the cluster. fncli reads secrets (the Gitea admin password, the Secrets a NodeSecret reads) from the **current context**, so check `kubectl config current-context` is the cluster you mean.
- A `.dev.env`, which fncli finds by searching up from your current directory. It holds only the deploy settings (`NAMESPACE` among them), the first Keycloak user and the optional GitHub ids: `.dev.env.example` documents them.
- A nexus-api login: fncli logs in as `FN_USERNAME` / `FN_PASSWORD` (in `.dev.env` or the shell), and asks for whichever is unset. It never picks a user itself. Revoking needs an Administrator; `verify-git-secret`, `merge-results-pr` and `fncli demo` mint repository git tokens, which only the System user (`dagster`, its password in the `dagster-keycloak-creds` secret) may do. On the dev cluster the node itself is described by Kubernetes resources in `config/`, which `kubectl apply` makes real (the nexus operator syncs them to nexus-api, ADR 0032). Which node fncli talks to (and the defaults of `fncli trigger`) is in `bootstrap/context.yaml` (`cp bootstrap/examples/context.yaml bootstrap/context.yaml`).

### The short way

```bash
fncli experiment deploy                       # the experiments release; the dev project's stand-in dataset reads the demo database's login
fncli gitea setup -f config/gitea.yaml -f config/e2e/fn-dev.yaml   # the Gitea repos of the dev project, and the Secrets with their OAuth apps
kubectl apply -f config/gitea.yaml -f config/e2e/dev-dataset.yaml -f config/e2e/fn-dev.yaml   # provider, dataset, secrets, repos, project
kubectl get fn -n fn-operator                          # each resource's Synced and Message; wait for every row to be synced
fncli start-sensor --group all                # start the twelve sensors
fncli trigger triggers/examples/demo.json --project fn-dev --pr --merge   # open and merge a pull request with a trigger file
fncli project-show --project fn-dev | jq                       # watch it: project resources, pull requests, tasks, results
kubectl delete -f config/e2e/fn-dev.yaml -f config/e2e/dev-dataset.yaml   # delete it all again (dev only; Gitea repos stay)
```

The files in `config/` are Kubernetes custom resources (group `fn.aridhia.com/v1alpha1`: GitProvider, NodeSecret, Repository, Dataset, Project), described with examples in [ADR 0032](project/decisions/0032-declarative-node-config-through-an-operator.md). A NodeSecret says where a secret's values are read from (a Kubernetes Secret, never the value in the file); a Repository or Project names what it uses, and the operator reports in its status why it cannot sync yet (a secret or dataset that is not there). `kubectl get fn -n fn-operator` lists each resource's Synced and Message; `kubectl diff -f FILE` shows what an apply would change. The operator creates what is missing, changes what differs and, on `kubectl delete`, soft-deletes the record in nexus-api: a global resource another project still uses stays `Terminating`, with the reason in its Message, until the project is deleted. The dev flows have one file per use: `config/gitea.yaml` (the provider), `config/demo.yaml`, `config/github/demo-github.yaml`, `config/experiments/*.yaml` and `config/e2e/*.yaml`.

`fncli gitea setup -f FILE [--rotate NODESECRET]` is the one step kubectl cannot do. It creates the Gitea repositories of the file's Repository resources and, for each NodeSecret they name, a Gitea OAuth app named after the NodeSecret, and writes `CLIENT_ID`, `CLIENT_SECRET` and `REFRESH_TOKEN` into the Kubernetes Secret the NodeSecret's `fromSecret` names. A Secret that exists is kept unless you pass `--rotate`. Run it before `kubectl apply` of the same file. Secrets from other sources are made with `kubectl create secret` (the GitHub App's, in [SETUP_GIT_APPS.md](SETUP_GIT_APPS.md)). Which node fncli talks to is in `bootstrap/context.yaml` (or `--context FILE`, `FNCLI_CONTEXT`): `fncli` refuses to run when `kubectl` points at another cluster.

`fncli demo --project demo-gitea` (or `demo-github`) walks the pull request part one step at a time, on a node where `kubectl apply` has set up `config/demo.yaml` (after `fncli gitea setup -f config/gitea.yaml -f config/demo.yaml`) or `config/github/demo-github.yaml`. It reads the Project resource and stops, showing the operator's message, unless it is synced. Before each step it says what the step does and shows the command, then asks: Enter runs it, `s` skips it, `q` quits. It adds the trigger file `triggers/examples/demo.json` in a pull request, or the one you name after the command. It creates and deletes nothing: `kubectl delete -f config/demo.yaml` cleans up. It uses its own project and repository names, so it never touches your test project.

### API step to fncli

| API step | In the node config (`config/`) | Run with |
|---|---|---|
| Secrets (git tokens) | a NodeSecret with `fromSecret`; the Secret is made by `fncli gitea setup` (a Gitea OAuth app) or `kubectl create secret` | `fncli gitea setup`, `kubectl apply` |
| Secret (dataset login) | a NodeSecret with `values` (each one a `secretKeyRef`) | `kubectl apply` |
| Git provider, trigger repository, results repository | a GitProvider and Repositories | `kubectl apply` |
| Dataset | a Dataset | `kubectl apply` |
| Project and its resources | a Project (the operator creates it disabled, enables it last) | `kubectl apply` |
| Enable | the Project's `enabled` | `kubectl apply` (a `project-set --enabled` on a project the operator manages is put back on its next change, ADR 0032) |
| Check | | `project-healthcheck`, `verify-project` |
| Start sensors | | `start-sensor --group all` |
| Open and merge a spec pull request | a trigger file (`triggers/`) | `trigger FILE --pr --merge` |
| Merge the results pull request | | `merge-results-pr --number N` |

### Operating the dev cluster with fncli

These act on the project named by `--project NAME`, or the context's `defaults.project` (the first line says when it is used), and talk only to nexus-api and Dagster. They read the project's repositories and datasets from the node. They are written for the dev cluster. On another node they may work if you point the context file's `node.url` and `DAGSTER_URL` at it and set the kube context, but that is untested. The `--revoked` options need an Administrator login (`FN_USERNAME`).

| Command | What it does |
|---|---|
| `sensor-status` | Every sensor's status and last three ticks (success, skip reason or error) |
| `start-sensor` / `stop-sensor` (`--group G` or `--name N`) | Starts or stops sensors; a group stops in reverse order |
| `project-show` | JSON of the project's resources, pull requests, tasks and results |
| `project-set --enabled/--revoked true\|false [--backfill]` | Enables, disables, revokes or restores a project (`--revoked` is admin only) |
| `resource-set KIND --enabled/--revoked ...` | The flags on a project resource (a project's use of a global resource). `KIND` is `trigger`, `results`, `dataset` or `secret` |
| `global-set KIND --enabled/--revoked ...` | The flags on the global resource itself |
| `secret-set --entity ... --enabled ...` | Turns a secret on or off, and with it everything that uses it |
| `project-healthcheck`, `verify-project` | The project's healthcheck, and its datasets; exit 1 on a failure |

### What not to do with it

- **On a real node, set up the git provider, repositories and secrets with the API.** `kubectl apply` of `config/` and `fncli gitea setup` are written for the dev and demo clusters: a node you care about gets its configuration through the chart values (ADR 0032).
- **Never `kubectl delete` `config/` files against a node you care about.** It deletes the project, its dataset, repositories and secrets (their stored values too).
- A project's dataset is whatever its `datasets:` entry names, and may be one that another file made. `fncli experiment deploy` renders each experiment database's Dataset and NodeSecret (namespace `experiments`); `fncli experiment setup uc1` waits for the UC1 dataset to sync, then runs `fncli gitea setup` and `kubectl apply` of `config/experiments/uc1.yaml` (its repositories and project).

## Switch things on and off

Two flags sit on every resource. **Enabled** is a switch anyone allowed to manage it can flip. **Revoked** is admin only and takes effect at once. A resource is **active** only when it is enabled and not revoked, and only active ones are used.

| To stop | Do this |
|---|---|
| A whole project | `PATCH /projects/<id>` with `{"enabled": false}`, or `{"revoked": true}` (admin) |
| One project's use of one resource | `PATCH` the project resource: `/projects/<id>/datasets/<dataset_id>`, `/projects/<id>/repositories/triggers/<id>`, `/projects/<id>/repositories/results/<id>` |
| A resource for every project | `PATCH /global/datasets/<id>`, `/global/repositories/triggers/<id>`, `/global/repositories/results/<id>` or `/global/providers/<id>` with `enabled` or `revoked` |
| A credential | `PATCH /global/secrets/<label>`. Disabling it also disables the datasets and repositories that use it, and moves its value to the quarantine namespace. They stay off when you turn the secret back on |

What happens to work in flight: the launcher fails a pending task, with the cause in its `state_cause`, when anything it uses is revoked or deleted. A result for a revoked or deleted results repository is recorded as `REVOKED` and nothing is delivered. A result for a disabled one is retried once it is switched back on.

`DELETE` is a soft delete: the record leaves the API and its project resources go with it, and the name is free again. Deleting a dataset or repository that projects still use is a `409` listing them, unless you add `?force=true`. The full table of what each state does is in [docs/architecture/revoke-and-enabled.md](docs/architecture/revoke-and-enabled.md).

## Add another project

A second project reuses the global resources: create the project, then assign the same ids.

```bash
PROJECT2_ID=$(curl -sS -X POST "$FN/projects" "${AUTH[@]}" -d '{"name": "second-project"}' | jq -r .id)

curl -sS -X PUT "$FN/projects/$PROJECT2_ID/datasets/$DATASET_ID" "${AUTH[@]}" -d '{}'
curl -sS -X PUT "$FN/projects/$PROJECT2_ID/repositories/triggers/$TRIGGER_ID" "${AUTH[@]}" -d '{"watch_dir": "specs/", "base_branch": "main"}'
curl -sS -X PUT "$FN/projects/$PROJECT2_ID/repositories/results/$RESULTS_ID" "${AUTH[@]}" -d '{"target_dir": "results-two/", "base_branch": "main"}'
curl -sS -X PATCH "$FN/projects/$PROJECT2_ID" "${AUTH[@]}" -d '{"enabled": true}'
```

A merged pull request is stored once, whatever the number of projects watching the repository, and each project whose `watch_dir` and `base_branch` match gets its own trigger and task. The project's own dataset resource decides which dataset its tasks use. `kubectl apply -f config/e2e/qa-two.yaml` does this on the dev cluster (the project `qa-two`, on the dev project's repositories and dataset).

## Checking on it

| Question | Where to look |
|---|---|
| Can everything be reached? | `GET /global/healthcheck`, `GET /projects/<id>/healthcheck`, and per resource `GET /global/datasets/<id>/healthcheck`, `/global/secrets/<label>/healthcheck`, `/global/providers/<id>/healthcheck`, `/global/repositories/triggers/<id>/healthcheck`, `/global/repositories/results/<id>/healthcheck` |
| What is this project doing? | `fncli project-show --project NAME`, or `GET /projects/<id>/tasks` |
| Is a run stuck or failing? | Dagster UI, **Runs**, for the logs of each step |
| Are the sensors running? | `fncli sensor-status`, or the Dagster UI **Automation** page |
| Whole-node checklist | [project/QA/deploy-and-health.md](project/QA/deploy-and-health.md) |

A pull request was merged and nothing happened:

| Cause | How you see it |
|---|---|
| Sensors are stopped (the default) | `sensor-status`: `STOPPED` |
| The project is disabled, or a project resource is inactive | `project-show`: `enabled` false or `revoked` true |
| The pull request does not add a `.json` file under `watch_dir`, or targets another branch | No trigger is made for that project (it is skipped and logged) |
| It was merged before the trigger repository was assigned or the project enabled | Skipped by design. Enable with `backfill`, or merge a new one |
| The spec is not valid | The trigger is `REJECTED` and `state_cause` says why |
| A token is wrong or expired | The resource's healthcheck fails and names it. Rotate it with `PATCH /global/secrets/<label>` |
| The task stays pending | `state_cause` on the task: usually the dataset resource is inactive or its secret is disabled. Fix the cause, then `POST /projects/<id>/tasks/<task_id>/retry` |
