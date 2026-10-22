# A bare Debian laptop for scripts/sandbox.sh: Docker (the installer's one prerequisite),
# sudo and git, nothing else. scripts/install-dev.sh installs the rest.
# Build context is scripts/, to share the dind start script with proxy-sim.
FROM docker:dind AS dind

FROM debian:13

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg sudo git \
      iptables iproute2 pigz xz-utils kmod procps xfsprogs e2fsprogs \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian trixie stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
 && apt-get purge -y curl gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# A normal user with sudo and docker access, like a developer's account.
# .cache is created here: sandbox.sh mounts the host pip cache into it, and Docker would
# otherwise create it as root.
RUN useradd -m -s /bin/bash -G sudo,docker dev \
 && echo 'dev ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dev \
 && install -d -o dev -g dev /home/dev/fn /home/dev/.cache /home/dev/.cache/pip

# Sets up the cgroups a nested Docker needs, then runs dockerd (same as the docker:dind image).
COPY --from=dind /usr/local/bin/dind /usr/local/bin/dind
COPY proxy-sim/laptop-start.sh /usr/local/bin/laptop-start

ENTRYPOINT ["laptop-start"]
