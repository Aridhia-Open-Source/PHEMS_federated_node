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

- `fncli setup-project`
- `fncli start-sensor --sensor all`
- `fncli open-pr --kind watched --merge`
- `fncli open-pr --kind unwatched --merge`
- `fncli open-pr --kind invalid --merge`
- `fncli sensor-status`
- `fncli project-healthcheck`
- `fncli teardown-project -y`

## What to expect

- `setup-project`: the healthcheck is `ok`.
- Ingest tick: "Saved N new pull requests to database".
- Watched PR: `YIELDED` with a Task, then the run succeeds.
- Unwatched PR: `IGNORED`.
- Invalid PR: `REJECTED`, with the validation error.
- `teardown-project -y`: nothing is left behind.
