# fncli examples

## Run the project from scratch

Run from the repo root.

- `kubectl config use-context kind-fn && kubectl config current-context`
- `make teardown`
- `make helm_deps`
- `make deploy`
- `tilt up --stream` (in a second terminal; wait until it's green)
- `pipx install --force --editable './dagster[cli]'`

## Test the trigger → task → run flow

Each section is one step. Run them in order, or use the optional group
commands to run a whole section at once.

fncli calls three things. Each line below says which:

- **Backend**: the federated-node backend API, shown as `METHOD /uri`.
- **Gitea**: the Gitea API, called directly (not through the backend).
- **Dagster**: the Dagster webserver.

fncli logs in first with `POST /login` on the backend, then makes its backend calls.

### 1. Set up the dev project

- `fncli setup-project`
  - Backend: `GET /projects`, then `POST /projects` if the test project is missing.
  - Gitea: creates the trigger repo and the results repo if they don't exist.
  - Gitea: issues a token for each repo (`POST /users/{user}/tokens`).
  - Backend: stores each token as a secret (`POST /global/secrets`, or `PATCH /global/secrets/{label}` if it exists).
  - Backend: stores dummy dataset credentials as a secret (same call).
  - K8s: reads the secret back to check it holds the new token.
  - Backend: registers the trigger repo (`POST /global/repositories/triggers`) if it is missing, then assigns it to the project (`PUT /projects/{id}/repositories/triggers/{repository_id}`).
  - Backend: registers the results repo (`POST /global/repositories/results`) if it is missing, then assigns it to the project (`PUT /projects/{id}/repositories/results/{repository_id}`).
  - Backend: registers the dataset (`POST /global/datasets`) if it is missing, then assigns it to the project (`PUT /projects/{id}/datasets/{dataset_id}`), which makes it the project's default if it is the first.
  - Gitea: checks each token is accepted.
  - Backend: `GET /projects/{id}/healthcheck`.

Optional, to set up one side only:

- `fncli setup-backend`: backend calls only (project, placeholder secrets, trigger repo, results repo, dataset). No Gitea, so the secrets hold placeholders.
- `fncli setup-gitea`: Gitea calls only (repos and tokens), plus `PATCH /global/secrets/{label}` on the backend to store the tokens. Takes `--project`.

### 2. Start the sensors

- `fncli start-sensor --sensor all`
  - Dagster: starts the run-status sensors first, then the results delivery sensor (it also acts when a run succeeds, so it must be running before the launcher) and the results PR sync sensor.
  - Dagster: starts the other sensors (ingest, evaluate, launcher).
  - Dagster: does nothing for a sensor that is already running.

Optional: `--sensor ingest|evaluate|launcher|status|delivery` starts just one (`status` is the run-status sensors, `delivery` is `task_results_delivery_sensor` and `results_pull_request_sync_sensor`, which records the results PR of a pushed result and keeps each results PR's state (OPENED, MERGED, CLOSED) up to date).

### 3. Open pull requests in the trigger repo

Each command opens a PR and merges it, using the Gitea API only. fncli makes no backend call here. The merge is what the ingest sensor later picks up, and the sensor is what calls the backend.

- `fncli open-pr --kind watched --merge`
  - Gitea: creates a branch, commits a file that matches the trigger's watched paths, opens the PR and merges it.
  - Expect a Task and a run.
- `fncli open-pr --kind unwatched --merge`
  - Gitea: the same, with a file outside the watched paths.
  - Expect no trigger for it: the PR is not listed for the link (`--watch` times out, as it waits for the PR to show up).
- `fncli open-pr --kind invalid --merge`
  - Gitea: the same, with a file that fails validation.
  - Expect it to be rejected.

Add `--watch` to follow the merged PR in real time (and `--timeout <seconds>`, default 300). It prints a timestamped line each time something changes (including a link to the Dagster run once it starts), and exits 1 on REJECTED, a FAILURE or CANCELED run, or a timeout. On a timeout it also lists the sensors that are not running at the stage it is stuck at. A dropped connection (Dagster reloading, say) is retried; it gives up after 10 failed polls in a row.

- `fncli open-pr --kind watched --merge --watch`, or `fncli merge-gitea-pr --number <n> --watch`
  - Backend: `GET /projects/{project_id}/repositories/triggers/{repository_id}/pull_requests`, until the PR shows up ("waiting for ingest") and shows its state (UNKNOWN, then YIELDED or REJECTED, with its state_cause).
  - Backend: `GET /projects/{project_id}/tasks/{task_id}` for a YIELDED PR, showing the task's status.
  - Dagster: GraphQL `runsOrError` filtered by the task_id tag, showing the run's id and status until SUCCESS, FAILURE or CANCELED.
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

Optional, check that every merged PR of the trigger repo ran in Dagster and the backend agrees:

- `fncli verify-repo`
  - Prints a block per PR, one line per check (`ok` or `FAIL`), and a summary. Exits 1 if any check fails.
  - `link` lines give the trigger PR in Gitea, the Dagster run and the results PR, as URLs that open from the host. They are not checks.
  - Backend: `GET /projects/{project_id}/repositories/triggers/{repository_id}/pull_requests`, for every PR of the project's link to the repository.
  - A PR the sensor rejected has no task, so it passes with a note.
  - A PR still `UNKNOWN` fails: the evaluate sensor hasn't run on it.
  - For a `YIELDED` PR, Backend: `GET /projects/{project_id}/tasks/{id}`, for the task's status, run id, attempt and times.
  - For a `YIELDED` PR, Dagster: finds the run tagged with the task's id, and checks it is a `k8s_pipes_job`.
  - Checks the task's status, run id and attempt match the run, and that `started_at` and `completed_at` are set when they should be.
  - Checks the run succeeded.
  - For a succeeded run, Backend: `GET /projects/{project_id}/tasks/{id}/results`, and checks the task has exactly one results delivery, its results PR was opened (state `OPENED`, `MERGED` or `CLOSED`; a failed delivery shows its error), it has a `commit_sha`, and it has a results PR (number and url; its state is shown).
  - Does not check the files in the results repo: it only reads the backend and Dagster.
- `fncli verify-repo --tail 10`
  - The same, for only the last 10 PRs by number.
- `merge-gitea-pr --watch` and `open-pr --merge --watch` print the same per-PR checks when the run ends. After a succeeded run they first wait up to 60s for the delivery to open its results PR (state `OPENED` or later) or fail (an error is recorded), printing a `Delivery:` line each time its state changes (Backend: `GET /projects/{project_id}/tasks/{id}/results`). If it does not finish, they name the delivery sensor if it is not running, and the delivery check fails.

### 5. Tear down

- `fncli teardown-project -y`
  - Backend: `DELETE /projects/{id}`, which also removes the tasks, triggers and the dataset, results repository and trigger repository assignments under it. Datasets, results repositories and secrets are global and stay.
  - Backend: the per-record deletes that follow (`DELETE /global/datasets/{id}`, `DELETE /global/repositories/triggers/{id}`, `DELETE /global/repositories/results/{id}`, `DELETE /global/secrets/{label}`) delete what is left (a record already gone is skipped). `DELETE /global/datasets/{id}` and `DELETE /global/repositories/results/{id}` also drop any remaining assignments, and need each project they are assigned to locked and drained.
  - Gitea: deletes the tokens (`DELETE users/{user}/tokens/{name}`).
  - Gitea: deletes both repos (`DELETE repos/{user}/{name}`).
  - Does not prompt, because of `-y`.

Optional, to tear down one side only:

- `fncli teardown-backend`: the backend deletes only.
- `fncli teardown-gitea`: the Gitea deletes only.

## What to expect

- `setup-project`: the healthcheck is `ok`.
- Ingest tick: "Saved N new pull requests to database", one poll per trigger repository however many projects are assigned to it.
- Watched PR: `YIELDED` with a Task, then the run succeeds.
- Unwatched PR: no trigger (the PR list for the link has only the watched and the invalid PR).
- Invalid PR: `REJECTED`, with the validation error.
- `teardown-project -y`: nothing is left behind.
