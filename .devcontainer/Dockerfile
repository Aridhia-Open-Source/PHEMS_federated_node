# The dev container's image: devcontainer.json builds it, and a plain
# `docker build .devcontainer` builds the same thing (`scripts/configure.sh --devcontainer`
# must have run first).
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The proxy CA (PROXY_CA_SETUP.md), trusted by the steps below and by the container.
# `configure.sh --devcontainer` writes proxy-ca.crt before the build: the host's CA bundle
# (system roots plus the proxy CA), or an empty file when there is none. update-ca-certificates
# puts every certificate of a file in the system bundle, but links only single-certificate files
# for lookups by hash (openssl rehash skips the rest), so the bundle is split into one file per
# certificate first.
COPY proxy-ca.crt /tmp/proxy-ca.crt
RUN if [ -s /tmp/proxy-ca.crt ]; then \
      csplit -s -z -f /usr/local/share/ca-certificates/fn-proxy-ca- -b '%04d.crt' \
        /tmp/proxy-ca.crt '/-----BEGIN CERTIFICATE-----/' '{*}' \
      && update-ca-certificates; \
    fi \
 && rm /tmp/proxy-ca.crt

# What the Python packages need to build (psycopg2 and friends)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq-dev build-essential \
 && rm -rf /var/lib/apt/lists/*

# mise installs everything else (mise.toml), at create time: `mise run setup`
RUN curl -fsSL https://mise.run | MISE_INSTALL_PATH=/usr/local/bin/mise sh

# vscode owns its tool and kube folders: the fn-mise-data volume takes its ownership from here.
# The kubeconfig overlay makes fn the namespace of kind-fn (see KUBECONFIG in devcontainer.json).
RUN install -d -o vscode -g vscode \
      /home/vscode/.local /home/vscode/.local/share /home/vscode/.local/share/mise /home/vscode/.kube
COPY --chown=vscode:vscode kube-overlay.yaml /home/vscode/.kube/overlay
