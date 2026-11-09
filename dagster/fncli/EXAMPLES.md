# fncli examples

## Run the project from scratch

Run from the repo root.

- `kubectl config use-context kind-fn && kubectl config current-context`
- `mise run teardown`
- `mise run helm-deps`
- `mise run deploy`
- `tilt up --stream` (in a second terminal; wait until it's green)
- `pipx install --force --editable './dagster[cli]'`

## Test the trigger → task → run flow

Each section is one step. Run them in order. `apply` does the whole of the first one.

fncli calls three things. Each line below says which:

- **Backend**: the federated-node backend API, shown as `METHOD /uri`.
- **Gitea**: the Gitea API, called directly (not through nexus-api).
- **Dagster**: the Dagster webserver.

fncli logs in first with `POST /login` on nexus-api, then makes its backend calls.

### Quick happy-path check

Every command that talks to the node reads `bootstrap/context.yaml` first (`cp bootstrap/examples/context.yaml bootstrap/context.yaml`). The commands that work on a project (`verify-project`, `project-show`, `open-pr`, `merge-results-pr`, ...) take `--project NAME`, else the context's `defaults.project`, and read its repositories and dataset from the node. The examples below are for the e2e project: `export FNCLI_DEFAULT_PROJECT=fn-dev` once, or add `--project fn-dev` to each.

To watch the pull request part one confirmed step at a time, run `fncli apply -f examples/globals-gitea.yaml` and `fncli apply -f examples/projects/demo-gitea.yaml`, then `fncli demo -f examples/projects/demo-gitea.yaml` (see Demo in [README.md](README.md)), then `fncli delete -f examples/projects/demo-gitea.yaml` and `fncli delete -f examples/globals-gitea.yaml --all`. The demo creates and deletes nothing.

A PR in the Gitea trigger repo, through a task, to a merged results PR in the Gitea results repo:

```bash
fncli apply -f examples/globals-e2e.yaml -y && fncli apply -f examples/projects/e2e.yaml -y && fncli verify-project
fncli start-sensor --group all
fncli trigger triggers/examples/demo.json --project fn-dev --pr --merge --watch --timeout 300

# Every minute or so:
fncli project-show | jq '{prs: .trigger_resources[0].pull_requests | map({number,state,task_id}), tasks: .tasks | map({id,status}), results: .results | map({number,step,state})}'
```

Wait for, in order: the PR `YIELDED` with a `task_id`, the task `SUCCESS`, then a result with `step` `OPENED` (delivery pushes it to `PUSHED`, then the results PR sensor opens the PR). Then:

```bash
fncli merge-results-pr --number "$(fncli project-show | jq '.results[0].number')"
# About a minute later the result's step is MERGED
fncli verify-project && fncli verify-repo
```

The same flow is automated from the repo root with `pytest dagster --e2e success -v` (the quick failure paths: `--e2e failure`, the long-running ones: `--e2e failure_long`, all of them: `--e2e`; put it after the path; the project is cleared at the start of each run and kept afterwards; `E2E_TEARDOWN=1` also tears it down at the end).

If something sticks: `fncli sensor-status`, and nexus-api and Dagster pod logs.

### 1. Set up the dev project

- `fncli diff -f examples/globals-e2e.yaml` shows what the next step would do, and changes nothing. The same for `examples/projects/e2e.yaml`, once the global file is applied.
- `fncli apply -f examples/globals-e2e.yaml`, then `fncli apply -f examples/projects/e2e.yaml` (each asks, `-y` does not). Each first checks that kubectl points at the context's cluster. In this order:
  - Backend: `GET` of every secret, provider, repository, dataset and project, to compare with the file.
  - Backend: stores each secret that is missing (`POST /global/secrets`): the OAuth credentials of a Gitea application it has made and authorised for the admin user (Gitea: `POST user/applications/oauth2`, then the authorisation over HTTP), or the values it read from the places the file names. A secret that exists is left alone (`--rotate LABEL` rewrites it: `PATCH /global/secrets/{label}`).
  - Backend: registers the Gitea host as a git provider (`POST /global/providers`) if it is missing, or changes what differs (`PATCH /global/providers/{id}`).
  - Gitea: creates the trigger repo and the results repo if they don't exist (when the file has a `gitea:` section with `create_repositories`).
  - Backend: registers the trigger repo (`POST /global/repositories/triggers`, with the provider's id and the repo's `owner/name` path) and the results repo (`POST /global/repositories/results`) if they are missing.
  - Backend: registers the dataset (`POST /global/datasets`) if it is missing.
  - Backend: creates the project disabled (`POST /projects`), assigns the datasets in the file's order (`PUT /projects/{id}/datasets/{dataset_id}`, the first becomes the default), the trigger repos (`PUT /projects/{id}/repositories/triggers/{repository_id}`) and the results repo (`PUT /projects/{id}/repositories/results/{repository_id}`), and enables it (`PATCH /projects/{id}`).
  - An assignment that exists is changed with `PATCH` and only the fields that differ, never `PUT`, which would reset its `enabled`.
- `fncli verify-git-secret --entity trigger` and `--entity results`: asks nexus-api for a token and calls Gitea with it.
- `fncli project-healthcheck`: Backend `GET /projects/{id}/healthcheck`.

### 2. Start the sensors

- `fncli start-sensor --group all`
  - Dagster: starts the run-status sensors, the reconcile sensor, the results delivery sensor and the results PR sync sensor.
  - Dagster: starts the other sensors (ingest, evaluate, launcher). The order does not matter.
  - Dagster: does nothing for a sensor that is already running.

Optional: `--group ingest|evaluate|launcher|status|delivery` starts just one group, or `--name <sensor>` just one sensor (`status` is the run-status sensors and `task_reconcile_sensor`, `delivery` is `task_results_delivery_sensor`, `results_delivery_retry_sensor` and `results_pull_request_sync_sensor`, which opens the results PR of a pushed result (stop it for a push-only node) and keeps each results PR's state (OPENED, MERGED, CLOSED) up to date).

### 3. Open pull requests in the trigger repo

Each command opens a PR and merges it, using the Gitea API only (`trigger` reads the project's trigger repository record from the backend first, `open-pr` reads it from `.dev.env`). The merge is what the ingest sensor later picks up, and the sensor is what calls nexus-api.

- `fncli trigger triggers/examples/demo.json --project fn-dev --pr --merge`
  - Backend: `GET` of the project and its trigger repository assignment, for the repository, watch directory and base branch.
  - Gitea: creates a branch, commits the trigger file under the watch directory, opens the PR and merges it.
  - Expect a Task and a run.
  - The project and the way (`--pr`) can be left out when the context's `defaults` name them; the first line then says so.
- `fncli open-pr --kind watched --merge`
  - The same by the names in `.dev.env`, with the default trigger file `triggers/examples/demo.json` (`--trigger FILE` for another).
- `fncli open-pr --kind unwatched --merge`
  - Gitea: the same, with a file outside the watched paths.
  - Expect no trigger for it: the PR is not listed for the project resource (`--watch` times out, as it waits for the PR to show up).
- `fncli open-pr --kind invalid --merge`
  - Gitea: the same, with a file that fails validation.
  - Expect it to be rejected.

Add `--watch` to follow the merged PR in real time (and `--timeout <seconds>`, default 300). It prints a timestamped line each time something changes (including a link to the Dagster run once it starts), and exits 1 on REJECTED, a FAILURE or CANCELED run, or a timeout. On a timeout it also lists the sensors that are not running at the stage it is stuck at. A dropped connection (Dagster reloading, say) is retried; it gives up after 10 failed polls in a row.

- `fncli trigger FILE --pr --merge --watch`, `fncli open-pr --kind watched --merge --watch`, or `fncli merge-gitea-pr --number <n> --watch`
  - Backend: `GET /projects/{project_id}/repositories/triggers/{repository_id}/pull_requests`, until the PR shows up ("waiting for ingest") and shows its state (UNKNOWN, then YIELDED or REJECTED, with its state_cause).
  - Backend: `GET /projects/{project_id}/tasks/{task_id}` for a YIELDED PR, showing the task's status.
  - Dagster: GraphQL `runsOrError` filtered by the fn/task_id tag, showing the run's id and status until SUCCESS, FAILURE or CANCELED.
  - Exits 0 on SUCCESS.

Optional, the same thing in separate steps (`--kind` as above):

- `fncli create-gitea-branch`: `POST repos/{repo}/branches` on Gitea. Prints the branch name.
- `fncli commit-gitea-file --branch <branch> --kind watched`: `POST repos/{repo}/contents/{file}` on Gitea.
- `fncli create-gitea-pr --branch <branch> --kind watched`: `POST repos/{repo}/pulls` on Gitea.
- `fncli merge-gitea-pr --number <n>`: `POST repos/{repo}/pulls/{n}/merge` on Gitea.
- `fncli merge-results-pr --number <n>`: the same call on the results repo. `results_pull_request_sync_sensor` then patches the row to MERGED within about a minute; check with `fncli verify-repo --tail 1`.

### 4. Check the result

- `fncli sensor-status`
  - Dagster: shows every sensor's status.
  - Dagster: shows each sensor's last 3 ticks.
- `fncli project-healthcheck`
  - Backend: `GET /projects/{id}/healthcheck`, printed as JSON.
  - Exits 1 unless it is `ok`.

Optional, a read-only report on the project:

- `fncli verify-project`
  - Prints one line per check (`ok`, `FAIL` or `SKIP`) and a summary. Exits 1 if any check fails.
  - Backend: `POST /login`, `GET /projects`.
  - Backend: `GET /projects/{id}/healthcheck`, which reaches each trigger repo and the results repo with its stored token. Each repo gets a line with its status and latency.
  - Backend: `GET /projects/{id}/datasets`, `GET /global/datasets/{id}` and `GET /global/secrets/{label}`, for the dataset the healthcheck leaves out.
  - Creates and changes nothing.

Optional, check that every merged PR of the trigger repo ran in Dagster and nexus-api agrees:

- `fncli verify-repo`
  - Prints a block per PR, one line per check (`ok` or `FAIL`), and a summary. Exits 1 if any check fails.
  - `link` lines give the trigger PR in Gitea, the Dagster run and the results PR, as URLs that open from the host. They are not checks.
  - Backend: `GET /projects/{project_id}/repositories/triggers/{repository_id}/pull_requests`, for every PR of the project's trigger repository.
  - A PR the sensor rejected has no task, so it passes with a note.
  - A PR still `UNKNOWN` fails: the evaluate sensor hasn't run on it.
  - For a `YIELDED` PR, Backend: `GET /projects/{project_id}/tasks/{id}`, for the task's status, run id, attempt and times.
  - For a `YIELDED` PR, Dagster: finds the run tagged with the task's id, and checks it is a `k8s_pipes_job`.
  - Checks the task's status, run id and attempt match the run, and that `started_at` and `completed_at` are set when they should be.
  - Checks the run succeeded.
  - For a succeeded run, Backend: `GET /projects/{project_id}/tasks/{id}/results`, and checks the task has exactly one results delivery, its results PR was opened by the results PR sensor (state `OPENED`, `MERGED` or `CLOSED`; a failed delivery or PR opening shows its error), it has a `commit_sha`, and it has a results PR (number and url; its state is shown). With the results PR sensor stopped (a push-only node; read from `GET /dagster/sensors/results_pull_request_sync_sensor`) it checks that the results were pushed (`PUSHED`, `DELIVERED`) instead, and has no results PR to check.
  - Does not check the files in the results repo: it only reads nexus-api and Dagster.
- `fncli verify-repo --tail 10`
  - The same, for only the last 10 PRs by number.
- `merge-gitea-pr --watch`, `open-pr --merge --watch` and `trigger --merge --watch` print the same per-PR checks when the run ends. After a succeeded run they first wait up to 60s for the delivery to open its results PR (state `OPENED` or later) or fail (an error is recorded), printing a `Delivery:` line each time its state changes (Backend: `GET /projects/{project_id}/tasks/{id}/results`). If it does not finish, they name the delivery sensor if it is not running, and the delivery check fails.

### 5. Tear down

- `fncli delete -f examples/projects/e2e.yaml -y`, then `fncli delete -f examples/globals-e2e.yaml --all -y`
  - Backend: `DELETE /projects/{id}`, which also removes the tasks, triggers and the dataset, results repository and trigger repository assignments under it. A file with projects, without `--all`, does only that.
  - Backend: with `--all`, the deletes that follow (`DELETE /global/repositories/triggers/{id}`, `DELETE /global/repositories/results/{id}`, `DELETE /global/datasets/{id}`, `DELETE /global/secrets/{label}`, `DELETE /global/providers/{id}` (kept when other repositories are on it)). They soft delete, and never with `?force=true`: what a project outside the file still uses is a 409, skipped with the backend's message, and the command exits 1.
  - Gitea: nothing. The repos and the OAuth apps stay.
  - Does not prompt, because of `-y`.

## What to expect

- `apply`: the healthcheck is `ok`.
- Ingest tick: "Saved N new pull requests to database", one poll per trigger repository however many projects are assigned to it.
- Watched PR: `YIELDED` with a Task, then the run succeeds.
- Unwatched PR: no trigger (the PR list for the project resource has only the watched and the invalid PR).
- Invalid PR: `REJECTED`, with the validation error.
- `delete --all -y`: nothing is left in the backend, but the Gitea repos stay.
