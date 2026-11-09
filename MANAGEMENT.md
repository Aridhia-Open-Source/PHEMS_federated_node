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

From the repo root. You need Python 3.12+ and `pipx`.

```bash
pipx install --force --editable './dagster[cli]'
fncli hello-world        # prints "Hello, world!"
```

If the shell cannot find `fncli`, run `pipx ensurepath` and open a new terminal. The full install notes, troubleshooting and uninstall are in [dagster/fncli/README.md](dagster/fncli/README.md).

### What it needs

- The dev cluster running with Tilt up (`mise run deploy`, then `tilt up`: [DEPLOYMENT.md](DEPLOYMENT.md#run-it-locally)). That gives the port-forwards: nexus-api `localhost:5000`, Dagster `localhost:3000`, Gitea `localhost:4000`.
- `kubectl` pointing at the cluster. fncli reads secrets (the Dagster system login, the Gitea admin password, the first user) from the **current context**, so check `kubectl config current-context` is the cluster you mean.
- A `.dev.env`, which fncli finds by searching up from your current directory. `.dev.env.example` documents every variable; the ones that matter here are `NEXUS_API_URL`, `KEYCLOAK_NAMESPACE`, `NAMESPACE`, `GITEA_API_URI`, the `TEST_*` names of the project, repositories and watch directory, and `DEFAULT_PROJECT_DATASET`. The node itself is described by node files in `bootstrap/examples`, which `fncli apply` makes real, and which node that is (and the defaults of `fncli trigger`) is in `bootstrap/context.yaml` (`cp bootstrap/examples/context.yaml bootstrap/context.yaml`).

### The short way

```bash
fncli diff  -f examples/globals-e2e.yaml      # what applying the node file would change; reads only
fncli apply -f examples/globals-e2e.yaml      # the global resources of the dev project (shows the same, asks, then does it)
fncli apply -f examples/projects/e2e.yaml     # the dev project
fncli start-sensor --group all                # start the twelve sensors
fncli trigger triggers/examples/demo.json --project fn-dev --pr --merge   # open and merge a pull request with a trigger file
fncli project-show | jq                       # watch it: project resources, pull requests, tasks, results
fncli delete -f examples/projects/e2e.yaml; fncli delete -f examples/globals-e2e.yaml --all   # delete it all again (dev only; Gitea repos stay)
```

`examples/globals-e2e.yaml` is found under the nearest `bootstrap/` directory. A node file lists any of the providers, secrets (each value says where it is read from, never the value), repositories, datasets and projects of a node; what it names but does not hold (a project's repository or dataset) must be on the node already. Which node it is applied to is in `bootstrap/context.yaml` (or `--context FILE`, `FNCLI_CONTEXT`): `fncli` refuses to run when `kubectl` points at another cluster. `apply` creates what is missing, changes what differs (only the differing fields), never rewrites a secret that exists unless `--rotate LABEL`, and never deletes. `delete -f FILE` deletes only the file's projects; `--all` also deletes the global repositories, datasets, secrets and providers, and skips, with the backend's reason, whatever a project outside the file still uses. Both can be repeated after a failure.

`fncli demo -f examples/projects/demo-gitea.yaml` (or `demo-github.yaml`) walks the pull request part one step at a time, on a node that `fncli apply` has set up with `examples/globals-gitea.yaml` and then that file (it stops unless `fncli diff` shows nothing to change). Before each step it says what the step does and shows the command, then asks: Enter runs it, `s` skips it, `q` quits. It adds the trigger file `triggers/examples/demo.json` in a pull request, or the one you name after the command. It creates and deletes nothing: `fncli delete` of the two files cleans up. It uses its own project and repository names, so it never touches your test project.

### API step to fncli

| API step | In the node file | Run with |
|---|---|---|
| Secrets (git tokens) | `secrets:` with `gitea_oauth` (mints a Gitea OAuth app) or `values` read from env, a file or a cluster secret | `apply` |
| Secret (dataset login) | `secrets:` with `values` | `apply` |
| Git provider, trigger repository, results repository | `providers:`, `repositories:` | `apply` |
| Dataset | `datasets:` | `apply` |
| Project and its resources | `projects:` (created disabled, enabled last) | `apply` |
| Enable | `enabled:` of the project | `apply`, or `project-set --enabled true` |
| Check | | `project-healthcheck`, `verify-project` |
| Start sensors | | `start-sensor --group all` |
| Open and merge a spec pull request | a trigger file (`triggers/`) | `trigger FILE --pr --merge` |
| Merge the results pull request | | `merge-results-pr --number N` |

### Operating the dev cluster with fncli

These act on the project named by `TEST_PROJECT_NAME`, or `--project NAME`, and talk only to nexus-api and Dagster. They are written for the dev cluster. On another node they may work if you point `NEXUS_API_URL` and `DAGSTER_URL` at it and set the kube context, but that is untested. The `--revoked` options also need the `keycloak-first-user` secret (keys `EMAIL` and `PASSWORD`) that only `mise run deploy` creates, so on a real node revoke through the API instead.

| Command | What it does |
|---|---|
| `sensor-status` | Every sensor's status and last three ticks (success, skip reason or error) |
| `start-sensor` / `stop-sensor` (`--group G` or `--name N`) | Starts or stops sensors; a group stops in reverse order |
| `project-show` | JSON of the project's resources, pull requests, tasks and results |
| `project-set --enabled/--revoked true\|false [--backfill]` | Enables, disables, revokes or restores a project (`--revoked` is admin only) |
| `resource-set KIND --enabled/--revoked ...` | The flags on a project resource (a project's use of a global resource). `KIND` is `trigger`, `results`, `dataset` or `secret` |
| `global-set KIND --enabled/--revoked ...` | The flags on the global resource itself |
| `secret-set --entity ... --enabled ...` | Turns a secret on or off, and with it everything that uses it |
| `project-healthcheck`, `verify-project` | The project's healthcheck, and its dataset; exit 1 on a failure |

### What not to do with it

- **On a real node, set up the git provider, repositories and secrets with the API.** `apply` and `delete` are written for the dev and demo clusters, with the confirmation they ask for: using them on a node you care about needs a decision of its own (ADR 0018).
- **Never run `delete --all` against a node you care about.** It deletes the project, its global dataset, repositories and secrets (their stored values too).
- A node file's dataset is whatever its `datasets:` entry says, and a project may be assigned a dataset by name that another file made. `fncli experiment setup uc1` applies the UC1 dataset (`experiments/uc1/dataset.yaml`), its global resources (`bootstrap/examples/globals-uc1.yaml`) and then its project (`bootstrap/examples/projects/uc1.yaml`).

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

A merged pull request is stored once, whatever the number of projects watching the repository, and each project whose `watch_dir` and `base_branch` match gets its own trigger and task. The project's own dataset resource decides which dataset its tasks use. `fncli apply -f examples/projects/e2e-second-projects.yaml --project QaTwo` does this on the dev cluster.

## Checking on it

| Question | Where to look |
|---|---|
| Can everything be reached? | `GET /global/healthcheck`, `GET /projects/<id>/healthcheck`, and per resource `GET /global/datasets/<id>/healthcheck`, `/global/secrets/<label>/healthcheck`, `/global/providers/<id>/healthcheck`, `/global/repositories/triggers/<id>/healthcheck`, `/global/repositories/results/<id>/healthcheck` |
| What is this project doing? | `fncli project-show`, or `GET /projects/<id>/tasks` |
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
