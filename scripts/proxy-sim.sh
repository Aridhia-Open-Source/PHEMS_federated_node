#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Federated Node - Corporate proxy simulation
#
# Reproduces a hospital network where the only way out is a TLS-intercepting
# (MITM) proxy, and runs a colleague's first-time setup on it (make cluster up,
# make deploy, tilt up, fncli demo) to see what breaks.
#
#   laptop  - proxysim-laptop (scripts/proxy-sim/Dockerfile): Ubuntu with its own
#             Docker daemon, kind, helm, tilt, pipx. Its network has no route out.
#   mitm    - mitmproxy, the only container with a route out. It re-signs every
#             HTTPS connection with its own CA, like a corporate proxy does.
#
# Your own Docker daemon, kind cluster and registries are never touched. No host
# ports are published.
#
# What the laptop is at each stage (each recreates it, keeping its volumes):
#   up      a locked-down machine: no proxy configured anywhere
#   proxy   proxy env (HTTP(S)_PROXY, NO_PROXY=localhost,127.0.0.1) set machine-wide,
#           as on a managed laptop, but the proxy's CA is not trusted yet
#   trust   the proxy CA is in the OS trust store (what IT pushes to managed machines).
#           Tools that bring their own CA bundle (pip, certifi) still don't see it.
#
# Usage:
#   ./scripts/proxy-sim.sh up               # stage 1; DIRECT=1 for a control run with
#                                           #   normal internet and no proxy
#   ./scripts/proxy-sim.sh pull [image]     # docker pull inside the laptop
#   ./scripts/proxy-sim.sh proxy            # stage 2
#   ./scripts/proxy-sim.sh trust            # stage 3
#   ./scripts/proxy-sim.sh flow [--from N]  # copy the working tree in, run the first-time
#                                           #   steps, stop at the first failure
#   ./scripts/proxy-sim.sh shell            # a shell in the repo copy, to poke around
#   ./scripts/proxy-sim.sh build            # rebuild the laptop image
#   ./scripts/proxy-sim.sh down             # remove everything, including the volumes
#
# Via make: proxy-sim-up, -pull, -proxy, -trust, -flow, -shell, -build, -down.
#
# dind has no systemd, so the proxy is set as environment variables on the whole
# container, dockerd included: the same thing the docker.service.d/http-proxy.conf
# drop-in does on a real host. The flow keeps each step's output in /work/logs inside the
# laptop.
####################################################################################

cd "$(dirname "$0")/.."

COMMAND="${1:-}"
IMAGE="${2:-ghcr.io/jqlang/jq:latest}"

NETWORK="proxysim-lan"
SUBNET="10.77.0.0/24"
# A fixed address, not the container name: the kind node and build containers nested in
# the laptop do not always get the laptop's DNS, and would not find the name.
MITM_IP="10.77.0.2"
MITM="proxysim-mitm"
LAPTOP="proxysim-laptop"
LAPTOP_IMAGE="proxysim-laptop:latest"
CA_VOLUME="proxysim-mitm-ca"
CA_FILE="/home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.pem"
PROXY_URL="http://${MITM_IP}:8080"
VOLUMES=(proxysim-docker proxysim-containerd proxysim-work)

wait_for() {
  local what="$1"; shift
  for _ in $(seq 1 90); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "Timed out waiting for ${what}" >&2
  exit 1
}

build_image() {
  docker build -t "$LAPTOP_IMAGE" scripts/proxy-sim
}

# First argument is the network, the rest are docker run args (the proxy env).
start_laptop() {
  local net="$1"; shift
  docker rm -f "$LAPTOP" >/dev/null 2>&1 || true
  docker run -d --init --privileged --name "$LAPTOP" --network "$net" \
    -v proxysim-docker:/var/lib/docker \
    -v proxysim-containerd:/var/lib/containerd \
    -v proxysim-work:/work \
    -e USER=root \
    "$@" "$LAPTOP_IMAGE" >/dev/null
  wait_for "the laptop daemon" docker exec "$LAPTOP" docker info
}

require_proxy_network() {
  docker network inspect "$NETWORK" >/dev/null 2>&1 || {
    echo "No proxy network: this laptop was started with DIRECT=1. Run down, then up." >&2
    exit 1
  }
}

case "$COMMAND" in
  build)
    build_image
    ;;

  up)
    docker image inspect "$LAPTOP_IMAGE" >/dev/null 2>&1 || build_image
    if [ -n "${DIRECT:-}" ]; then
      start_laptop bridge
      echo "Up on a normal network, no proxy (control run). Try: $0 flow"
      exit 0
    fi
    docker network inspect "$NETWORK" >/dev/null 2>&1 || \
      docker network create --internal --subnet "$SUBNET" "$NETWORK" >/dev/null
    if ! docker inspect "$MITM" >/dev/null 2>&1; then
      docker run -d --name "$MITM" -v "${CA_VOLUME}:/home/mitmproxy/.mitmproxy" \
        mitmproxy/mitmproxy mitmdump --listen-port 8080 --set block_global=false \
        --set stream_large_bodies=1m >/dev/null
      docker network connect --ip "$MITM_IP" "$NETWORK" "$MITM"
    fi
    wait_for "the mitm CA" docker exec "$MITM" test -f "$CA_FILE"
    start_laptop "$NETWORK"
    echo "Up. The laptop has no proxy configured. Try: $0 pull"
    ;;

  proxy)
    require_proxy_network
    start_laptop "$NETWORK" \
      -e "HTTP_PROXY=${PROXY_URL}" -e "HTTPS_PROXY=${PROXY_URL}" -e "NO_PROXY=localhost,127.0.0.1" \
      -e "http_proxy=${PROXY_URL}" -e "https_proxy=${PROXY_URL}" -e "no_proxy=localhost,127.0.0.1"
    echo "Laptop restarted with ${PROXY_URL} as its proxy. Try: $0 pull"
    ;;

  trust)
    require_proxy_network
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    docker cp "${MITM}:${CA_FILE}" "${tmp}/mitm.crt"
    docker cp "${tmp}/mitm.crt" "${LAPTOP}:/usr/local/share/ca-certificates/mitm.crt"
    docker exec "$LAPTOP" update-ca-certificates >/dev/null
    docker restart "$LAPTOP" >/dev/null
    wait_for "the laptop daemon" docker exec "$LAPTOP" docker info
    echo "Proxy CA installed in the laptop's system trust store. Try: $0 pull"
    ;;

  pull)
    docker exec "$LAPTOP" docker pull "$IMAGE"
    ;;

  sync)
    # The working tree, minus anything gitignored, so a run never writes into your checkout.
    docker exec "$LAPTOP" sh -c 'rm -rf /work/fn && mkdir -p /work/fn'
    git ls-files -z --cached --others --exclude-standard --deduplicate \
      | tar --null -T - --ignore-failed-read -cf - 2>/dev/null \
      | docker exec -i "$LAPTOP" tar -xf - -C /work/fn
    # dev.values.yaml is gitignored, so it is not in the copy. The example has no Gitea block
    # (the chart default is off), and the demo needs Gitea, so use the one that works here.
    if [ -f k8s/federated-node/dev.values.yaml ]; then
      docker cp k8s/federated-node/dev.values.yaml "${LAPTOP}:/work/fn/k8s/federated-node/dev.values.yaml"
    fi
    # A clone has a .git and deploy.sh asks git for the branch and sha, so give the copy one.
    docker exec -w /work/fn "$LAPTOP" sh -c \
      'git init -q && git add -A && git -c user.name=sim -c user.email=sim@localhost commit -qm sim'
    echo "Copied the working tree to /work/fn in the laptop."
    ;;

  flow)
    # Resuming with --from keeps the copy (and the config the earlier steps wrote).
    if [ "${2:-}" != "--from" ]; then "$0" sync; fi
    docker exec -w /work/fn "$LAPTOP" bash scripts/proxy-sim/flow.sh "${@:2}"
    ;;

  shell)
    docker exec -it -w /work/fn "$LAPTOP" bash
    ;;

  down)
    docker rm -f "$LAPTOP" "$MITM" >/dev/null 2>&1 || true
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
    docker volume rm "$CA_VOLUME" "${VOLUMES[@]}" >/dev/null 2>&1 || true
    echo "Removed."
    ;;

  *)
    echo "Usage: $0 <up|proxy|trust|pull [image]|flow [--from N]|shell|build|down>"
    exit 1
    ;;
esac
