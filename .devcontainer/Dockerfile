# The dev container's image: devcontainer.json builds it, and a plain
# `docker build .devcontainer` builds the same thing (host-ca.sh must have run first).
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The proxy CA (PROXY_CA_SETUP.md), trusted by the steps below and by the container.
# host-ca.sh writes proxy-ca.crt before the build: the CA, or an empty file when there is none.
COPY proxy-ca.crt /usr/local/share/ca-certificates/fn-proxy-ca.crt
RUN if [ -s /usr/local/share/ca-certificates/fn-proxy-ca.crt ]; then \
      update-ca-certificates; \
    else \
      rm /usr/local/share/ca-certificates/fn-proxy-ca.crt; \
    fi

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
