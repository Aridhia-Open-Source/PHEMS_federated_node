# 0034. Running behind a TLS-intercepting proxy

Status: Accepted, 2026-11-15.

## Context

- **Developers and sites sit behind proxies that re-sign HTTPS with their own CA.** Without that CA, `docker pull`, `pip`, `apt`, `curl`, `helm` and the node's own outbound calls fail with `x509: certificate signed by unknown authority`.
- **Several places each need the CA and the proxy:** the host's Docker daemon and client, image builds, the dev container, the kind node, and the pods (nexus-api, the Dagster code server and its run pods, Keycloak).
- **Tooling that edits files a developer also edits by hand** loses their changes or fights them.
- **The chart already takes `proxy.*` and `customCA`** for real clusters. The dev tooling needs to set the same values without touching hand-edited files.
- **Dagster's Kubernetes client ignored `NO_PROXY`,** so run pods sent calls to the cluster API through the proxy.

## Decision

One script sets up the machine side, and everything it writes is generated.

- **The CA is the system trust bundle by default.** Developers add the proxy's CA to their OS store themselves (on WSL, in the Linux store). `--ca-file PATH` installs a CA there first.
- **One script, `scripts/setup-proxy-ca.sh`, serves the host and the dev container.** The dev container's `initializeCommand` runs it with `--devcontainer`, on the host and without sudo, and it copies the bundle to `.devcontainer/proxy-ca.crt` for the image build.
- **It checks on every run, before it writes anything:** the bundle is PEM, a proxy is set, and `registry-1.docker.io`, `pypi.org` and `github.com` verify through the proxy against the bundle. With a CA and no proxy (a private git host) it checks the PEM only.
- **It writes only generated, gitignored files:** `.generated.env` (`CUSTOM_CA_FILE`, the proxy and CA-bundle variables) and `k8s/federated-node/generated.values.yaml` (the chart's `proxy.*` and `customCA.secretName`). It never edits `.dev.env` or `dev.values.yaml`.
- **Generated files load first, so hand-edited ones win:** `scripts/load_env.sh` (sourced by the cluster scripts), `mise.toml` and the Tiltfile read `.generated.env` before `.dev.env`, and `mise run deploy` passes `generated.values.yaml` before `dev.values.yaml`. A variable set in both is named in one warning.
- **Image builds get the CA as the BuildKit secret `proxy_ca`,** mounted on each download step (pip, and the others) and never kept in an image. `apk` uses http repositories, which it verifies by package signature.
- **Real clusters set `proxy.*` and `customCA` in their own values.** The script is dev tooling only.
- **Dagster is on 1.13.3 and dagster-k8s 0.29.3,** where the Kubernetes client honours `NO_PROXY`, instead of a local patch.
- **It is tested against mitmproxy** (`scripts/proxy-sim.sh` for the dev container and image builds, `scripts/proxy-sim-sensors.sh` for the pull request pipeline on the dev cluster): with no CA or a wrong one the step fails with a certificate error, with the right one it passes.

## Consequences

- A new download step in a Dockerfile needs the `proxy_ca` mount, or it fails behind a proxy.
- `--undo` removes what the script added: the CA, the Docker proxy settings and the two generated files.
- The kind node's own image pulls through the proxy are untested.
- The local registry mirrors that `mise run cluster up` starts get the proxy variables but not the CA.
- A `CUSTOM_CA_FILE` set by hand in `.dev.env` creates the Secret on deploy, but the pods use it only once `customCA.secretName` names it in `dev.values.yaml`.

## Alternatives considered

- **Kind inside nested Docker for the simulation:** it makes the cluster's network look like a site's, but it is far too slow to run.
- **Patching the Kubernetes client for `NO_PROXY`:** dropped for the upstream fix in dagster-k8s 0.29.3.
- **Exporting the CA from the Windows store on WSL:** developers manage their own WSL trust store, so the script does not reach into Windows.
- **Editing `dev.values.yaml` with `yq`:** the script runs before mise installs any tools, and generated files leave the hand-edited ones untouched.
- **A base image with the CA baked in:** the CA is specific to a site, so every site would build its own base.
