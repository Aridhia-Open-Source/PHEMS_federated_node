# The fake hospital laptop for scripts/proxy-sim.sh: Ubuntu with its own Docker daemon and
# the tools DEPLOYMENT.md asks for. Everything is installed here, at image build time on the
# normal network, so the only network the flow itself needs is the one behind the proxy.
FROM docker:dind AS dind

FROM ubuntu:24.04

# v0.30.0 makes node v1.34. v0.31.0 (node v1.35, containerd 2 with config_path) rejects the
# `registry.mirrors` patches in .kind/kind-config.yaml, so cluster up fails on a fresh machine.
ARG KIND_VERSION=v0.30.0
ARG HELM_VERSION=v3.19.0
ARG TILT_VERSION=0.37.5

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git make jq bash vim-tiny openssl \
      python3 python3-venv pipx \
      iptables iproute2 pigz xz-utils kmod procps xfsprogs e2fsprogs \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSLo /usr/local/bin/kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64" \
 && curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
 && curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" | tar -xz -C /usr/local/bin --strip-components=1 linux-amd64/helm \
 && curl -fsSL "https://github.com/tilt-dev/tilt/releases/download/v${TILT_VERSION}/tilt.${TILT_VERSION}.linux.x86_64.tar.gz" | tar -xz -C /usr/local/bin tilt \
 && chmod +x /usr/local/bin/kind /usr/local/bin/kubectl

# Sets up the cgroups a nested Docker needs, then runs dockerd (same as the docker:dind image).
COPY --from=dind /usr/local/bin/dind /usr/local/bin/dind

COPY laptop-start.sh /usr/local/bin/laptop-start

ENV PATH=/root/.local/bin:${PATH}
WORKDIR /work
ENTRYPOINT ["laptop-start"]
