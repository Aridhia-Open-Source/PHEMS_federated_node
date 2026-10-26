# 0018. fncli as a dev/ops tool

## Context

Setting up a project (backend project, secrets, git provider, trigger and results repositories, Gitea repositories and tokens, a dataset), producing test pull requests and starting the sensors takes many manual calls.

## Decision

`dagster/fncli` is a click CLI (`pipx install --editable './dagster[cli]'`) of idempotent step commands per entity (project, repository, secret, dataset, pr, sensor, state, verify) and group commands (`setup-project`, `open-pr`, `teardown-project`, `setup-backend`, `setup-gitea`, `simulate-*`, ...). It speaks the global model: it creates global resources and assigns them to a project ([0006](0006-global-resources-and-project-resources.md)). It talks to the backend (port 5000), Gitea (4000, [0019](0019-gitea-port-4000-and-localhost-forward.md)), the Dagster GraphQL API (3000, to start, stop and inspect sensors) and the cluster (secrets through the kubeconfig). `open-pr --kind watched|unwatched|invalid` produces the evaluation outcomes; `merge-results-pr` drives a results pull request to `MERGED`. `start-sensor --group all` starts every sensor, in any order ([0014](0014-dagster-pipeline-ops-sensors-and-retries.md)).

## Consequences

- It is **not** a product interface: it is for development and demos on the Tilt cluster, assumes the port-forwards, and its Gitea and token handling are test-oriented (dummy dataset credentials, tokens minted per run).
- fncli is a second package in `dagster/pyproject.toml` (the `cli` extra) and imports the backend, Gitea and model code from `dagster/app`; there are no copies. What only the CLI needs lives in `dagster/fncli` as subclasses or small modules.
- Limited tests (the CLI wiring and commands, and an end-to-end suite); no coverage of a live cluster in the unit tests.

## Alternatives considered

- **Make targets and shell scripts:** not composable or testable.
