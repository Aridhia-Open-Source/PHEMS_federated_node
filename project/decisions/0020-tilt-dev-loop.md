# 0020. Tilt dev loop, with the tilt-run image for run pods

## Context

A rebuild-and-redeploy loop takes minutes. The Dagster code runs in two kinds of pod: the code server (live-updatable), and run pods that Dagster's launcher starts from `DAGSTER_CURRENT_IMAGE`, which a live update does not touch.

## Decision

- Helm (`make deploy`) owns all Kubernetes resources; Tilt (`Tiltfile`) only builds images and attaches live update and port-forwards. It watches `localhost:5001/webserver-fn` (Flask, synced `webserver/app`) and `localhost:5001/dagster-fn` (synced `dagster/app`, restart wrapper). Dependency or config file changes fall back to a full rebuild.
- `dagster-run-image` rebuilds and pushes `dagster-fn:tilt-run` on each `dagster/` change; `scripts/tilt_manifests.py` points `DAGSTER_CURRENT_IMAGE` at it, and run pods always pull, so the next run uses the new code.
- `dagster-reload` polls the Dagster GraphQL API and reloads the code location whenever it is not loaded (a rebuilt pod, or a code server the webserver gave up on), retrying for 60s before it reports a failure. It does not watch files: a reload fired at save time hits the old or a half-started server.
- Only what the code server and run pods use (`dagster/app` without tests, `requirements.txt`, `pyproject.toml`, `dagster.yaml`, `workspace.yaml`, `Dockerfile`) rebuilds the Dagster images. `fncli`, tests and docs do not.
- Port-forwards: backend 5000, Dagster UI 3000, Postgres 5432 and datasets DB 5433, Gitea 4000, Keycloak 8080. Each section of the Tiltfile adds its URL to `DEV_URLS`; `dagster-reload` prints the list and gives each entry a Tilt link.

## Consequences

- The edit-to-run loop is seconds; the `deliver_results_job` and `k8s_pipes_job` run pods see code changes.
- The chart and Tilt both define the Dagster gRPC command; the Tiltfile must keep an empty entrypoint and not clear the chart's args.
- Dev only: production uses the chart's images.

## Alternatives considered

- **Skaffold or a manual docker build:** no per-file live update.
- **Only live-update the code server:** run pods would run stale code.
