# The fake hospital laptop for scripts/proxy-sim.sh: Ubuntu with its own Docker daemon and
# mise. Docker and mise are installed here, at image build time on the normal network. The flow
# then runs `mise run setup` behind the proxy, which downloads kind, kubectl, helm and tilt.
FROM docker:dind AS dind

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git make jq bash vim-tiny openssl \
      build-essential libpq-dev \
      iptables iproute2 pigz xz-utils kmod procps xfsprogs e2fsprogs \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
 && rm -rf /var/lib/apt/lists/*

# mise, for `mise run setup` and every `mise run` task. It installs the pinned tools into
# ~/.local/share/mise; the shims on PATH below put them on the path of non-login shells too.
RUN curl -fsSL https://mise.run | MISE_INSTALL_PATH=/usr/local/bin/mise sh

# Sets up the cgroups a nested Docker needs, then runs dockerd (same as the docker:dind image).
COPY --from=dind /usr/local/bin/dind /usr/local/bin/dind

COPY laptop-start.sh /usr/local/bin/laptop-start

ENV PATH=/root/.local/share/mise/shims:/root/.local/bin:${PATH}
WORKDIR /work
ENTRYPOINT ["laptop-start"]
