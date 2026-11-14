# Troubleshooting: Dagster sensors hang in the proxy simulation

Notes from reviewing `wip/proxy-ca-setup` (last commit `3a104343`). The review was done by reading
`scripts/proxy-sim-sensors.sh`, the chart helpers and the Dagster code. Nothing was run, so the
causes below are hypotheses until the checks at the end are done on a machine with the dev cluster.

## State of the branch

- `scripts/proxy-sim-sensors.sh` is a set of manual steps (`up`, `probe`, `deploy`, `setup`, `pr`,
  `status`, `down`), not a self-checking test. Nothing in the last commit shows the three runs
  (no CA, wrong CA, mitmproxy's CA) passed on the cluster.
- `PROXY_CA_SETUP.md` documents only the three quick tests in `scripts/proxy-sim.sh`, not this script.

## What is wired correctly

- The Dagster code server and run pods get `HTTPS_PROXY`/`NO_PROXY` from `fn.proxy.env` in
  `k8s/federated-node/templates/_helpers.tpl`, plus the custom CA volumes.
- `NO_PROXY` starts with `.svc`, `.cluster.local` and `$(KUBERNETES_SERVICE_HOST)`, so calls between
  the node's own services skip the proxy.
- Task (pipes) pods deliberately get neither the proxy nor the CA.

## Likely hang points

1. **No request timeout.** `dagster/app/gitea.py`, `github.py` and `backend.py` set no timeout (the
   shared base client may; not checked). A stalled request to `https://gitea.proxysim.test` would hang
   the sensor tick instead of failing. This would make the `none` and `wrong` runs hang rather than
   fail fast with a certificate error. mitmproxy runs with `connection_strategy=lazy` and `--map-remote`.
2. **Daemon/webserver have no proxy.** Sensors are evaluated in the code server, so this should be fine.
   If the code server cannot reach the daemon or its own gRPC port, check `NO_PROXY` first.
3. **Unpinned image.** `mitmproxy/mitmproxy:latest` is loaded into kind with `imagePullPolicy: Never`,
   so a stale or changed image can behave differently from what the script was written against.
4. **Nothing waits.** `setup` and `pr` do not wait for a sensor tick, so a run can sit waiting for a
   result that never comes.

## Checks to run (on the dev cluster)

```bash
./scripts/proxy-sim-sensors.sh probe     # curl through the proxy: fails without the CA, works with it
./scripts/proxy-sim-sensors.sh status    # TLS errors in the logs, and what crossed the proxy
kubectl logs deployment/proxysim -n proxysim --tail=50
```

| Result | Meaning |
|---|---|
| `probe` passes and `status` shows requests reaching mitmproxy | The proxy is fine; the sensor waits on something else (check the code server logs) |
| `probe` hangs | The problem is mitmproxy or the map-remote rule |
| Nothing crossed the proxy | The sensor never made the call: check the code server's env and the project's `https://gitea.proxysim.test` URI |

Also note which of the three runs (none, wrong, right) it hung on.

## Possible fixes to try

- Give the Gitea/GitHub/backend clients an explicit `timeout=` so a stall fails the tick.
- Pin the mitmproxy image tag.
- Make the script wait for the sensor tick and fail with a clear message after a deadline.
