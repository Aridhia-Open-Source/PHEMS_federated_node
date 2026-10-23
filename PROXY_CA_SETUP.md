# Setting up behind a TLS-inspecting proxy

Use this when your network sits behind a proxy that re-signs HTTPS traffic with its own certificate authority (CA), or when something the node talks to uses a private CA. One script does the machine side.

## Do you need this?

Yes, if you see errors like these:

- `x509: certificate signed by unknown authority` or `SSL certificate problem` on `docker pull`, `curl`, `pip` or `helm`
- pods stuck in `ImagePullBackOff` or `ErrImagePull`
- `502 Bad Gateway` when pulling from `kind-registry` or the local mirrors
- `TLS handshake timeout` that comes and goes (see the table at the end)

## What you need first

1. **The CA file**, in PEM format. Ask your IT team for the root or issuing CA of the proxy. It starts with `-----BEGIN CERTIFICATE-----`. A `.cer` or `.der` file converts with `openssl x509 -inform der -in file.cer -out ca.pem`.
2. **The proxy address**, for example `http://proxy.example.org:8080`. Your browser's proxy settings or `echo $HTTPS_PROXY` show it.
3. **Docker working** without sudo (`docker info`), and `sudo` rights on this machine.

## Run it

Preview first. It changes nothing:

```bash
./scripts/setup-proxy-ca.sh --ca-file /path/to/ca.pem --proxy http://proxy.example.org:8080 --dry-run
```

Then for real:

```bash
./scripts/setup-proxy-ca.sh --ca-file /path/to/ca.pem --proxy http://proxy.example.org:8080
```

It shows the CA's name and fingerprint and asks you to confirm. Check the fingerprint with your IT team if you are unsure. Add `--yes` to skip the questions.

Docker has to restart for the proxy setting to apply. **That stops every running container, including a kind cluster.** The script asks first.

Then open a new shell, or run `direnv allow`, so the new variables load. Continue with `./scripts/install-dev.sh` or `make cluster up`.

On a fresh machine you can do both in one go: `./scripts/install-dev.sh --ca-file /path/to/ca.pem --proxy http://proxy.example.org:8080`. It runs this script first, before it downloads anything.

## What it changes

| What | Where |
|---|---|
| The CA, trusted by the whole machine | `/usr/local/share/ca-certificates/fn-proxy-ca.crt` |
| The proxy for the Docker daemon | `/etc/systemd/system/docker.service.d/http-proxy.conf` |
| The proxy for `docker build`, and for containers you start | `proxies.default` in `~/.docker/config.json` |
| `CUSTOM_CA_FILE`, the proxy and the CA-bundle variables | a block marked `setup-proxy-ca` in `.dev.env` |

Containers you start with `docker run` get the proxy variables too. To remove all of it: `./scripts/setup-proxy-ca.sh --undo`.

The script runs a check at the end: `https://ghcr.io` must verify through the proxy, and a small `docker pull` must work. Run it again at any time. It skips what is already done.

If Docker is not a systemd service on your machine (Docker Desktop, rootless Docker), the script tells you the settings to put in Docker yourself.

## If something fails

| You see | It means | Do this |
|---|---|---|
| `x509: certificate signed by unknown authority` | Docker or the tool does not trust the CA yet | Restart Docker. Run the script again |
| The same error after the script passed | The file is not the proxy's CA, or an intermediate is missing | Ask IT for the full chain and use `--ca-file` with the bundle |
| `502 Bad Gateway` from `kind-registry` or `proxy-*-registry` | Requests for local names went through the proxy | `NO_PROXY` must list `kind-registry,proxy-docker-hub-registry,proxy-ghcr-registry`. The script sets it; check your own shell for an override |
| `could not resolve host`, `connection refused` | Wrong proxy address, or the proxy is not reachable | Check the address with `curl -x $HTTPS_PROXY -I https://example.com` |
| `TLS handshake timeout`, only for some pulls | The network path has a smaller packet size (a VPN, WSL2) | Lower Docker's MTU to match: `ip link` shows the value, set it as `"mtu"` in `/etc/docker/daemon.json`, restart Docker |
| `pip` says `SSL: CERTIFICATE_VERIFY_FAILED` | pip uses its own bundle | The script sets `PIP_CERT`. Make sure `.dev.env` is loaded in this shell |
| `make deploy` fails in `apt-get`, `apk` or `pip` while building an image | The build has no proxy or no CA | Run the script (it sets the Docker client proxy), make sure `CUSTOM_CA_FILE` is set in `.dev.env`, and use Docker 23 or later (BuildKit) |

## On a real cluster

On a production cluster you do not use the script. Put the CA in a Secret and name it in the Helm values (`customCA.secretName`). See "Custom CA" in [DEPLOYMENT.md](DEPLOYMENT.md#custom-ca).

## Known gaps

- Image builds get the CA as a BuildKit secret (`proxy_ca`) in the pip steps, and use http repositories for `apk` (apk checks package signatures itself). This is not tested end to end yet.
- The local registry mirrors that `make cluster up` starts get the proxy variables but not the CA yet.
