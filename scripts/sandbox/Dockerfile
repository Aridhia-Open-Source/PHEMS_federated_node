# A bare Debian laptop for scripts/sandbox.sh: Docker (the installer's one prerequisite),
# sudo and git, nothing else. scripts/install-dev.sh installs the rest.
# Build context is scripts/, to share the dind start script with proxy-sim.
FROM docker:dind AS dind

FROM debian:13

ENV DEBIAN_FRONTEND=noninteractive
# Dev tooling for a network that intercepts TLS (SANDBOX_CA_FILE in scripts/sandbox.sh).
# sandbox/ca/ holds the CA only when that is set; otherwise this layer is empty and nothing
# below changes. With a CA, apt switches to https and trusts the file for its first run,
# since ca-certificates is not installed yet; the CA then joins the system trust, which is
# what curl, pipx, helm and the inner dockerd's registry pulls read.
COPY sandbox/ca/ /tmp/sandbox-ca/
RUN APT_OPTS=""; \
    if [ -s /tmp/sandbox-ca/sandbox-ca.crt ]; then \
      sed -i 's|^URIs: http://|URIs: https://|' /etc/apt/sources.list.d/debian.sources; \
      APT_OPTS="-o Acquire::https::CaInfo=/tmp/sandbox-ca/sandbox-ca.crt"; \
    fi; \
    apt-get $APT_OPTS update && apt-get $APT_OPTS install -y --no-install-recommends \
      ca-certificates curl gnupg sudo git \
      iptables iproute2 pigz xz-utils kmod procps xfsprogs e2fsprogs \
 && if [ -s /tmp/sandbox-ca/sandbox-ca.crt ]; then \
      cp /tmp/sandbox-ca/sandbox-ca.crt /usr/local/share/ca-certificates/sandbox-ca.crt \
      && update-ca-certificates; \
    fi \
 && rm -rf /tmp/sandbox-ca \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian trixie stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
 && apt-get purge -y curl gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# A normal user with sudo and docker access, like a developer's account. sudo keeps the proxy and CA
# variables, so the installer's `sudo apt-get` uses the proxy the sandbox was started with.
# .cache is created here: sandbox.sh mounts the host pip cache into it, and Docker would
# otherwise create it as root.
RUN useradd -m -s /bin/bash -G sudo,docker dev \
 && echo 'dev ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dev \
 && echo 'Defaults env_keep += "http_proxy https_proxy no_proxy HTTP_PROXY HTTPS_PROXY NO_PROXY SSL_CERT_FILE CURL_CA_BUNDLE REQUESTS_CA_BUNDLE GIT_SSL_CAINFO"' > /etc/sudoers.d/proxy \
 && chmod 0440 /etc/sudoers.d/proxy \
 && install -d -o dev -g dev /home/dev/fn /home/dev/.cache /home/dev/.cache/pip

# Sets up the cgroups a nested Docker needs, then runs dockerd (same as the docker:dind image).
COPY --from=dind /usr/local/bin/dind /usr/local/bin/dind
COPY proxy-sim/laptop-start.sh /usr/local/bin/laptop-start

ENTRYPOINT ["laptop-start"]
