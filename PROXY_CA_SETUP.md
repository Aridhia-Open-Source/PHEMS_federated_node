# Setting up behind a TLS-inspecting proxy

Use this when your network sits behind a proxy that re-signs HTTPS traffic with its own certificate authority (CA), or when something the node talks to uses a private CA. One command, `mise run configure` (`scripts/configure.sh`), does the machine side, and the same script serves the dev container. Every run first creates `.dev.env` and `dev.values.yaml` from the examples if they are missing; with no options that is all it does.

## Do you need this?

Yes, if you see errors like these:

- `x509: certificate signed by unknown authority` or `SSL certificate problem` on `docker pull`, `curl`, `pip` or `helm`
- pods stuck in `ImagePullBackOff` or `ErrImagePull`
- `502 Bad Gateway` when pulling from `kind-registry` or the local mirrors
- `TLS handshake timeout` that comes and goes (see the table at the end)

## What you need first

1. **The proxy address**, for example `http://proxy.example.org:8080`. Your browser's proxy settings or `echo $HTTPS_PROXY` show it. `--proxy` with no value uses `HTTPS_PROXY`. `--ca-cert` without `--proxy` (a private git host with its own CA) sets up the CA only, with no proxy, and checks the CA only.
2. **The proxy's CA, in your system trust store.** The script uses the system CA bundle (`/etc/ssl/certs/ca-certificates.crt`, or `/etc/pki/tls/certs/ca-bundle.crt` on Red Hat family systems), so sites the proxy does not intercept still verify. If your machine already trusts the proxy's CA (on WSL, for example, you may have added it to the Linux store yourself), you need nothing else. If not, ask your IT team for the CA file, in PEM format (the root or issuing CA of the proxy; it starts with `-----BEGIN CERTIFICATE-----`) and pass it with `--ca-cert=FILE`. A `.cer` or `.der` file converts with `openssl x509 -inform der -in file.cer -out ca.pem`.
3. **Docker working** without sudo (`docker info`), and `sudo` rights on this machine.

## Run it

Preview first. It changes nothing:

```bash
mise run configure --proxy=http://proxy.example.org:8080 --dry-run
```

Then for real:

```bash
mise run configure --proxy=http://proxy.example.org:8080
```

If the proxy's CA is not in your system store yet, add `--ca-cert=/path/to/ca.pem`: the script then shows the CA's name and fingerprint, asks you to confirm (check the fingerprint with your IT team if you are unsure), and installs it into the system store. Add `--yes` to skip the questions. Values always take the `=` form.

For a private CA and no proxy (a private git host): `mise run configure --ca-cert=/path/to/ca.pem`, or `--ca-cert` alone if your system store already trusts it.

`mise run deploy` gives the chart the CA in `CUSTOM_CA_FILE` as `customCA.pem`, whether `--ca-cert` or you set it.

Docker has to restart for the proxy setting to apply. **That stops every running container, including a kind cluster.** The script asks first.

Then open a new shell so the new variables load (`mise run` loads `.generated.env` itself). Continue with `mise run setup` (install [mise](https://mise.jdx.dev/) first on a fresh machine; run `./scripts/configure.sh --proxy=URL` before that, so its download verifies), then `mise run cluster up`.

## The checks

Every `--proxy` or `--ca-cert` run does these first, before anything is written (`--dry-run` included):

1. The CA bundle is a PEM file with at least one certificate.
2. With a proxy: `registry-1.docker.io`, `pypi.org` and `github.com` verify through the proxy, using the bundle (with `--ca-cert=FILE`, the system bundle plus that CA, since it is not installed yet). Any HTTP status passes: the TLS handshake is what matters, and Docker Hub answers `401` here. With a CA and no proxy this check is skipped.

A failing check names the host and says whether it is a certificate problem (the bundle does not match what the proxy presents) or a proxy or connection problem (the address, or no route to it). The script then exits with an error and has changed nothing. `--no-proxy` and `--no-ca` run no checks.

## In the dev container

The dev container calls the same script. Its `initializeCommand` runs `scripts/configure.sh --devcontainer` on your machine before the image is built (see [DEPLOYMENT.md](DEPLOYMENT.md#dev-container)). It reads `CUSTOM_CA_FILE` and the proxy from `.dev.env`, else from `.generated.env`, runs the checks above, and copies the bundle to `.devcontainer/proxy-ca.crt` (not committed). The image build splits it into one file per certificate and adds them to the container's system trust. It needs no sudo and writes nothing else, apart from creating `.dev.env` and `dev.values.yaml` if they are missing. With no `CUSTOM_CA_FILE` in either file it skips the checks and the container gets no CA.

So run the script on the machine first, then rebuild the container (**Dev Containers: Rebuild Container**) after any change.

## What it changes

| What | Where |
|---|---|
| The CA, trusted by the whole machine (only with `--ca-cert=FILE`) | `/usr/local/share/ca-certificates/fn-proxy-ca.crt` |
| The proxy for the Docker daemon | `/etc/systemd/system/docker.service.d/http-proxy.conf` |
| The proxy for `docker build`, and for containers you start | `proxies.default` in `~/.docker/config.json` |
| `CUSTOM_CA_FILE` (the system bundle, with the proxy's CA in it), the proxy and the CA-bundle variables | `.generated.env` in the repo root |
| The chart's `proxy.httpProxy` and `proxy.httpsProxy` | `k8s/federated-node/generated.values.yaml` |

The script owns the last two files and rewrites them whole each run; both are gitignored, and neither is edited by hand. It never edits your `.dev.env` or `dev.values.yaml`. Everything that loads settings (`mise run`, the scripts, Tilt) reads `.generated.env` first and `.dev.env` after it, and `mise run deploy` passes `generated.values.yaml` before `dev.values.yaml`, so what you wrote yourself wins. If `.dev.env` sets a variable the script generates, the script warns once and names it.

Containers you start with `docker run` get the proxy variables too. To remove the proxy: `mise run configure --no-proxy` (the Docker settings, the proxy in the generated files, and the block that an older version of the script kept in `.dev.env`). To remove the CA too: `mise run configure --no-proxy --no-ca` (the CA in the trust store; `--no-ca` alone refuses while a proxy is set, since the proxy needs it). A run that changes only the proxy or only the CA keeps the other as `.generated.env` has it; with neither left, the two generated files are deleted.

At the end a small `docker pull` must work. Run the script again at any time. It skips what is already done.

If Docker is not a systemd service on your machine (Docker Desktop, rootless Docker), the script tells you the settings to put in Docker yourself.

## If something fails

| You see | It means | Do this |
|---|---|---|
| `x509: certificate signed by unknown authority` | Docker or the tool does not trust the CA yet | Restart Docker. Run the script again |
| The same error after the script passed | The file is not the proxy's CA, or an intermediate is missing | Ask IT for the full chain and pass it with `--ca-cert=FILE` |
| `502 Bad Gateway` from `kind-registry` or `proxy-*-registry` | Requests for local names went through the proxy | `NO_PROXY` must list `kind-registry,proxy-docker-hub-registry,proxy-ghcr-registry`. The script sets it; check your own shell for an override |
| `could not resolve host`, `connection refused` | Wrong proxy address, or the proxy is not reachable | Check the address with `curl -x $HTTPS_PROXY -I https://example.com` |
| `TLS handshake timeout`, only for some pulls | The network path has a smaller packet size (a VPN, WSL2) | Lower Docker's MTU to match: `ip link` shows the value, set it as `"mtu"` in `/etc/docker/daemon.json`, restart Docker |
| `pip` says `SSL: CERTIFICATE_VERIFY_FAILED` | pip uses its own bundle | The script sets `PIP_CERT`. Make sure `.generated.env` is loaded in this shell |
| `mise run deploy` fails in `apt-get`, `apk` or `pip` while building an image | The build has no proxy or no CA | Run the script (it sets the Docker client proxy), make sure `CUSTOM_CA_FILE` is set in `.generated.env`, and use Docker 23 or later (BuildKit) |

## On a real cluster

On a production cluster you do not use the script. Put the CA in a Secret and name it in the Helm values (`customCA.secretName`). See "Custom CA" in [DEPLOYMENT.md](DEPLOYMENT.md#custom-ca).

## Testing it

`scripts/proxy-sim.sh` runs three quick tests behind mitmproxy, on a Docker network whose only way out is the proxy. Each runs with no CA, a wrong CA and mitmproxy's CA: the first two must fail with a certificate error, the last must pass with its requests in mitmproxy's log. The script checks this itself.

- `mise run proxy-sim-setup`: builds the dev container image with the CA, then runs `mise run setup` in it on a copy of the working tree.
- `mise run proxy-sim-build`: builds the nexus-api image (`--all` for every image) with the CA as the `proxy_ca` build secret. Nothing is pushed.
- `mise run proxy-sim-pull`: `docker pull` in a stock `docker:dind` that trusts the CA.

Add `--mode none|wrong|right` to run one mode. `mise run proxy-sim-down` removes it all. Your own images, cluster and registry are not touched.

`scripts/proxy-sim-sensors.sh` tests the Dagster pull-request pipeline the same way, on the dev cluster (it deploys the release, so this checkout must own the cluster). mitmproxy runs as a pod, and the in-cluster Gitea is registered under an outside-looking HTTPS name that only the proxy answers, so every call, clone and push crosses it. With no CA or a wrong CA the pipeline fails with a certificate error; with mitmproxy's CA as `customCA` the merged pull request is ingested and the results pull request is opened. The steps are at the top of the script.

## Known gaps

- Image builds get the CA as a BuildKit secret (`proxy_ca`) in the pip steps, and use http repositories for `apk` (apk checks package signatures itself). `mise run proxy-sim-build` tests the nexus-api image.
- The local registry mirrors that `mise run cluster up` starts get the proxy variables but not the CA yet.
