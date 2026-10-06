# fncli examples

## Run the project from scratch

Run from the repo root.

- `kubectl config use-context kind-fn && kubectl config current-context`
- `make teardown`
- `make helm_deps`
- `make deploy`
- `tilt up --stream` (in a second terminal; wait until it's green)
- `pipx install --force --editable scripts/fncli`

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
  - Backend: stores each token as a project secret (`POST /projects/{id}/secrets`, or `PATCH /projects/{id}/secrets/{label}` if it exists).
  - Backend: stores dummy dataset credentials as a project secret (same call).
  - K8s: reads the secret back to check it holds the new token.
  - Backend: registers the trigger repo (`POST /trigger_repositories`).
  - Backend: registers the results repo (`POST /results_repositories`).
  - Backend: registers the dataset (`POST /datasets`).
  - Gitea: checks each token is accepted.
  - Backend: `GET /projects/{id}/healthcheck`.

Optional, to set up one side only:

- `fncli setup-backend`: backend calls only (project, placeholder secrets, trigger repo, results repo, dataset). No Gitea, so the secrets hold placeholders.
- `fncli setup-gitea`: Gitea calls only (repos and tokens), plus `PATCH /projects/{id}/secrets/{label}` on the backend to store the tokens. Takes `--project`.

### 2. Start the sensors

- `fncli start-sensor --sensor all`
  - Dagster: starts the run-status sensors first.
  - Dagster: starts the other sensors (ingest, evaluate, launcher).
  - Dagster: does nothing for a sensor that is already running.

Optional: `--sensor ingest|evaluate|launcher|status` starts just one (`status` is the run-status sensors).

### 3. Open pull requests in the trigger repo

Each command opens a PR and merges it, using the Gitea API only. fncli makes no backend call here. The merge is what the ingest sensor later picks up, and the sensor is what calls the backend.

- `fncli open-pr --kind watched --merge`
  - Gitea: creates a branch, commits a file that matches the trigger's watched paths, opens the PR and merges it.
  - Expect a Task and a run.
- `fncli open-pr --kind unwatched --merge`
  - Gitea: the same, with a file outside the watched paths.
  - Expect it to be ignored.
- `fncli open-pr --kind invalid --merge`
  - Gitea: the same, with a file that fails validation.
  - Expect it to be rejected.

Add `--watch` to follow the merged PR in real time (and `--timeout <seconds>`, default 300). It prints a timestamped line each time something changes, and exits 1 on REJECTED, a FAILURE or CANCELED run, or a timeout. On a timeout it also lists the sensors that are not running at the stage it is stuck at.

- `fncli open-pr --kind watched --merge --watch`, or `fncli merge-gitea-pr --number <n> --watch`
  - Backend: `GET /trigger_repositories/{repo_id}/pull_requests`, until the PR shows up ("waiting for ingest") and shows its state (UNKNOWN, then YIELDED, IGNORED or REJECTED, with its state_cause).
  - Backend: `GET /tasks/{task_id}` for a YIELDED PR, showing the task's status.
  - Dagster: GraphQL `runsOrError` filtered by the task_id tag, showing the run's id and status until SUCCESS, FAILURE or CANCELED.
  - Exits 0 on IGNORED or SUCCESS.

Optional, the same thing in separate steps (`--kind` as above):

- `fncli create-gitea-branch`: `POST repos/{repo}/branches` on Gitea. Prints the branch name.
- `fncli commit-gitea-file --branch <branch> --kind watched`: `POST repos/{repo}/contents/{file}` on Gitea.
- `fncli create-gitea-pr --branch <branch> --kind watched`: `POST repos/{repo}/pulls` on Gitea.
- `fncli merge-gitea-pr --number <n>`: `POST repos/{repo}/pulls/{n}/merge` on Gitea.

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
  - Backend: `GET /datasets`, `GET /datasets/{id}` and `GET /projects/{id}/secrets`, for the dataset the healthcheck leaves out.
  - Creates and changes nothing.

Optional, check that every merged PR of the trigger repo ran in Dagster and the backend agrees:

- `fncli verify-repo`
  - Prints a block per PR, one line per check (`ok` or `FAIL`), and a summary. Exits 1 if any check fails.
  - Backend: `GET /trigger_repositories/{id}/pull_requests`, for every PR.
  - A PR the sensor ignored or rejected has no task, so it passes with a note.
  - A PR still `UNKNOWN` fails: the evaluate sensor hasn't run on it.
  - For a `YIELDED` PR, Backend: `GET /tasks/{id}`, for the task's status, run id, attempt and times.
  - For a `YIELDED` PR, Dagster: finds the run tagged with the task's id, and checks it is a `k8s_pipes_job`.
  - Checks the task's status, run id and attempt match the run, and that `started_at` and `completed_at` are set when they should be.
  - Checks the run succeeded.
- `fncli verify-repo --tail 10`
  - The same, for only the last 10 PRs by number.
- `merge-gitea-pr --watch` and `open-pr --merge --watch` print the same per-PR checks when the run ends.

### 5. Tear down

- `fncli teardown-project -y`
  - Backend: `DELETE /projects/{id}`, which also removes the tasks, datasets, repos and secrets under it.
  - Backend: the per-record deletes that follow (`DELETE /datasets/{id}`, `DELETE /trigger_repositories/{id}`, `DELETE /results_repositories/{id}`, `DELETE /projects/{id}/secrets/{label}`) find the record already gone and skip it.
  - Gitea: deletes the tokens (`DELETE users/{user}/tokens/{name}`).
  - Gitea: deletes both repos (`DELETE repos/{user}/{name}`).
  - Does not prompt, because of `-y`.

Optional, to tear down one side only:

- `fncli teardown-backend`: the backend deletes only.
- `fncli teardown-gitea`: the Gitea deletes only.

## What to expect

- `setup-project`: the healthcheck is `ok`.
- Ingest tick: "Saved N new pull requests to database".
- Watched PR: `YIELDED` with a Task, then the run succeeds.
- Unwatched PR: `IGNORED`.
- Invalid PR: `REJECTED`, with the validation error.
- `teardown-project -y`: nothing is left behind.
