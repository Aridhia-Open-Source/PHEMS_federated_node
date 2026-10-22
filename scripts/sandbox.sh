#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Federated Node - dev sandbox
#
# A throwaway Debian 13 laptop in Docker (scripts/sandbox/Dockerfile) with its own
# Docker daemon, for testing scripts/install-dev.sh as a fresh clone would run it.
# Your own Docker, kind cluster, registries and ports are never touched; the services
# are only reachable inside the sandbox.
#
#   ./scripts/sandbox.sh up          # create it if needed, copy the working tree in, run
#                                    #   the installer (again: syncs and reinstalls)
#   ./scripts/sandbox.sh down        # remove it; keeps its images and build cache
#                                    #   (NO_CACHE=1: remove those too)
#   ./scripts/sandbox.sh shell       # a shell in the repo copy
#   ./scripts/sandbox.sh <cmd...>    # run any command there, e.g. fncli project-show
#
# Via make: make sandbox up|down|shell, and SANDBOX=1 make <target> for any target.
#
# The copy is the working tree minus gitignored files, so .dev.env, dev.values.yaml
# and charts/ start missing, as in a clone. The code Tilt watches (LIVE_DIRS) is
# bind-mounted instead, so host edits live-reload in the sandbox. Anything else reaches
# it on the next `up`. The mounts are fixed when the sandbox is created: down, then up.
#
# Image pulls go through the host's pull-through mirrors (make cluster up on the host
# starts them), so a new sandbox does not download everything again. The sandbox joins
# the host's kind network; its Docker uses the host's Docker Hub mirror, its own
# mirrors fetch from the host's, and make deploy copies an image from the host's kind
# registry (localhost:5001 there) instead of building it when the sandbox's has none
# (UPSTREAM_REGISTRY in build_image.sh). Tilt still builds webserver and dagster.
# The host's pip cache (~/.cache/pip) is mounted too, for the fncli install.
# NO_CACHE=1 make sandbox up for a cold start (also fixed
# at creation: down, then up).
# SANDBOX_HOST_NETWORK_DOCKER_BUILD=1 builds the sandbox image on the host's network and
# passes this shell's proxy variables to it, for a host whose only way out is a proxy on
# its own localhost. Only the image build uses it, not the running sandbox.
#
# SANDBOX_CA_FILE=/path/ca.pem (dev tooling, best effort) is for a network that intercepts
# TLS. The CA is installed into the image's system trust (the image build switches apt to
# https and trusts the file for its first run), and the sandbox's shells get
# CURL_CA_BUNDLE, SSL_CERT_FILE, REQUESTS_CA_BUNDLE and GIT_SSL_CAINFO pointing at the
# system bundle, so install-dev.sh's curl, pipx and helm downloads verify against it. The
# inner Docker daemon reads the system trust for registry pulls. Verification is never
# switched off. Not covered: the kind node's own containerd, and images' own RUN steps. Fixed
# when the image is built and the sandbox created: down, then up. Unset, nothing changes.
####################################################################################

cd "$(dirname "$0")/.."

NAME=fn-sandbox
IMAGE=fn-sandbox:latest
VOLUMES=(fn-sandbox-docker fn-sandbox-containerd)
REPO=/home/dev/fn
# Tilt's docker_build contexts (Tiltfile), mounted from the host for live reload.
LIVE_DIRS=(webserver dagster)
DEV_PATH=/home/dev/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

TTY=(-i)
[ -t 0 ] && [ -t 1 ] && TTY=(-it)

SANDBOX_CA_INSTALLED=/usr/local/share/ca-certificates/sandbox-ca.crt
SANDBOX_CA_STAGE=scripts/sandbox/ca/sandbox-ca.crt

as_dev() {
  # Whether the image carries a SANDBOX_CA_FILE decides this, not the caller's environment,
  # so `shell` and commands trust it too.
  local var ca_env=()
  if docker exec "$NAME" test -f "$SANDBOX_CA_INSTALLED" 2> /dev/null; then
    for var in CURL_CA_BUNDLE SSL_CERT_FILE REQUESTS_CA_BUNDLE GIT_SSL_CAINFO; do
      ca_env+=(-e "$var=/etc/ssl/certs/ca-certificates.crt")
    done
    # The sandbox's own kind node and release trust it too (cluster.sh, custom_ca.sh).
    ca_env+=(-e "CUSTOM_CA_FILE=$SANDBOX_CA_INSTALLED")
  fi
  docker exec "${TTY[@]}" -u dev -w "$REPO" \
    -e USER=dev -e HOME=/home/dev -e PATH="$DEV_PATH" ${ca_env[@]+"${ca_env[@]}"} "$NAME" "$@"
}

# A host mirror's address on the host's kind network, empty if it is not running there.
host_mirror() {
  local ip
  ip="$(docker inspect -f '{{if .State.Running}}{{with index .NetworkSettings.Networks "kind"}}{{.IPAddress}}{{end}}{{end}}' "$1" 2> /dev/null || true)"
  [ -z "$ip" ] || echo "$ip:5000"
}

require_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2> /dev/null || true)" = "true" ] || {
    echo "No sandbox running. Start it with: make sandbox up" >&2
    exit 1
  }
}

case "${1:-}" in
  up)
    # SANDBOX_HOST_NETWORK_DOCKER_BUILD=1: the build's RUN steps use the host's network, for a host that
    # reaches the internet only through a proxy on its own localhost (a container cannot see that). The
    # proxy from this shell's environment replaces the one the Docker client config injects.
    build_args=()
    if [ -n "${SANDBOX_HOST_NETWORK_DOCKER_BUILD:-}" ]; then
      build_args=(--network host)
      # apt fetches over plain http, so HTTP_PROXY defaults to the HTTPS one (the Docker client config
      # would otherwise inject its own).
      https_proxy_url="${HTTPS_PROXY:-${https_proxy:-}}"
      http_proxy_url="${HTTP_PROXY:-${http_proxy:-$https_proxy_url}}"
      no_proxy_list="${NO_PROXY:-${no_proxy:-localhost,127.0.0.1}}"
      if [ -n "$https_proxy_url" ]; then
        for var in HTTPS_PROXY https_proxy; do build_args+=(--build-arg "$var=$https_proxy_url"); done
        for var in HTTP_PROXY http_proxy; do build_args+=(--build-arg "$var=$http_proxy_url"); done
        for var in NO_PROXY no_proxy; do build_args+=(--build-arg "$var=$no_proxy_list"); done
      fi
    fi
    # SANDBOX_CA_FILE: stage the CA in the build context (gitignored by *.crt), for the Dockerfile.
    rm -f "$SANDBOX_CA_STAGE"
    if [ -n "${SANDBOX_CA_FILE:-}" ]; then
      [ -s "$SANDBOX_CA_FILE" ] || { echo "SANDBOX_CA_FILE=$SANDBOX_CA_FILE is missing or empty" >&2; exit 1; }
      grep -q -e '-----BEGIN CERTIFICATE-----' "$SANDBOX_CA_FILE" \
        || { echo "SANDBOX_CA_FILE=$SANDBOX_CA_FILE holds no PEM certificate" >&2; exit 1; }
      cp "$SANDBOX_CA_FILE" "$SANDBOX_CA_STAGE"
      trap 'rm -f "$SANDBOX_CA_STAGE"' EXIT
      echo "Installing $SANDBOX_CA_FILE into the sandbox's system trust."
    fi
    docker build "${build_args[@]}" -t "$IMAGE" -f scripts/sandbox/Dockerfile scripts
    rm -f "$SANDBOX_CA_STAGE"
    if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2> /dev/null || true)" != "true" ]; then
      docker rm -f "$NAME" > /dev/null 2>&1 || true
      mounts=()
      for dir in "${LIVE_DIRS[@]}"; do mounts+=(-v "$PWD/$dir:$REPO/$dir"); done

      # By IP: containers nested in the sandbox do not get Docker's DNS for the kind network.
      cache=()
      # Google's Docker Hub mirror is the fallback when Docker Hub rate-limits (429).
      dockerd_args=(--registry-mirror https://mirror.gcr.io)
      hub="$(host_mirror proxy-docker-hub-registry)"
      ghcr="$(host_mirror proxy-ghcr-registry)"
      images="$(host_mirror kind-registry)"
      if [ -n "${NO_CACHE:-}" ]; then
        echo "NO_CACHE set: pulling everything from the internet."
      elif [ -n "$hub" ] && [ -n "$ghcr" ] && [ -n "$images" ]; then
        echo "Using the host's registries: Docker Hub $hub, GHCR $ghcr, images $images"
        cache=(--network kind -e "DOCKERHUB_UPSTREAM=http://$hub" -e "GHCR_UPSTREAM=http://$ghcr"
          -e "UPSTREAM_REGISTRY=$images")
        [ -d "$HOME/.cache/pip" ] && cache+=(-v "$HOME/.cache/pip:/home/dev/.cache/pip")
        dockerd_args=(--registry-mirror "http://$hub" --registry-mirror https://mirror.gcr.io
          --insecure-registry "$hub" --insecure-registry "$ghcr" --insecure-registry "$images")
      else
        echo "Host registries not running (make cluster up on the host): pulling and building everything."
      fi

      docker run -d --init --privileged --name "$NAME" --hostname "$NAME" \
        -v fn-sandbox-docker:/var/lib/docker \
        -v fn-sandbox-containerd:/var/lib/containerd \
        "${mounts[@]}" "${cache[@]}" \
        "$IMAGE" "${dockerd_args[@]}" > /dev/null
      echo "Waiting for the sandbox's Docker daemon..."
      for _ in $(seq 1 90); do
        docker exec "$NAME" docker info > /dev/null 2>&1 && break
        sleep 1
      done
      docker exec "$NAME" docker info > /dev/null
      # The Docker volumes outlive `down` to keep images and build cache. Clear what an
      # earlier sandbox left in them (kind node, registries, their data) so this starts fresh.
      docker exec "$NAME" sh -c 'docker rm -f $(docker ps -aq) 2>/dev/null; docker volume prune -af; docker network prune -f' > /dev/null
    fi

    echo "Copying the working tree to $REPO in the sandbox..."
    live_re="^($(IFS='|'; echo "${LIVE_DIRS[*]}"))/"
    git ls-files -z --cached --others --exclude-standard --deduplicate \
      | grep -zEv "$live_re" \
      | tar --null -T - --ignore-failed-read -cf - 2> /dev/null \
      | docker exec -i -u dev "$NAME" tar -xf - -C "$REPO"
    # A clone has a .git and deploy.sh asks git for the branch and sha.
    docker exec -u dev -w "$REPO" "$NAME" sh -c \
      'git init -q -b sandbox 2>/dev/null; git add -A && git -c user.name=sandbox -c user.email=sandbox@localhost commit -qm sync --allow-empty'

    as_dev ./scripts/install-dev.sh
    ;;

  down)
    docker rm -f "$NAME" > /dev/null 2>&1 || true
    if [ -n "${NO_CACHE:-}" ]; then
      docker volume rm "${VOLUMES[@]}" > /dev/null 2>&1 || true
      echo "Sandbox removed, with its images and build cache."
    else
      echo "Sandbox removed. Its images and build cache are kept (NO_CACHE=1 to remove them)."
    fi
    ;;

  shell)
    require_running
    TTY=(-it)
    as_dev bash -l
    ;;

  "")
    echo "Usage: $0 <up|down|shell|cmd...>"
    exit 1
    ;;

  *)
    require_running
    as_dev "$@"
    ;;
esac
