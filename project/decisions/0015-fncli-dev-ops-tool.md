# 0015. fncli as a dev/ops tool

- Status: Accepted (scope is deliberately small)

## Context

Setting up a project (backend project, secrets, trigger and results repositories, Gitea repos and tokens, a dataset), producing test pull requests and starting the sensors took many manual calls.

## Decision

`scripts/fncli` is a click CLI (`pipx install`) of idempotent step commands per entity (project, repository, secret, dataset, pr, sensor, verify) and group commands (`setup-project`, `open-pr`, `teardown-project`, `setup-backend`, `setup-gitea`, ...). It talks to the backend (port 5000), Gitea (4000, [0010](0010-gitea-port-4000-and-localhost-forward.md)), the Dagster GraphQL API (3000, to start/stop/inspect sensors) and the cluster (secrets through the kubeconfig). `open-pr --kind watched|unwatched|invalid` produces the three evaluation outcomes; `merge-results-pr` drives a results pull request to MERGED. `start-sensor all` starts sensors in the safe order ([0009](0009-sync-reconciler-and-operational-rules.md)).

## Consequences

- It is **not** a product interface: it is for development and demos on the Tilt cluster, assumes the port-forwards, and its Gitea and token handling are test-oriented (dummy dataset credentials, tokens minted per run).
- `scripts/fncli/dagster/` holds copies of backend, Gitea and model code from `dagster/app` so the package installs alone. The copies can drift and must be updated together.
- Limited tests (the CLI wiring and commands); no coverage of a live cluster.

## Alternatives considered

- **Make targets and shell scripts** (the earlier `scripts/gitea.sh`): not composable or testable.
- **Import `dagster/app`**: pulls in Dagster and shadows the `dagster` package, hence the copy under `fncli.dagster`.
