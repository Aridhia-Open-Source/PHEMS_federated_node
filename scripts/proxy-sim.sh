#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Federated Node - corporate proxy simulation
#
# A hospital network where the only way out is a TLS-intercepting (MITM) proxy, to check
# that the dev setup works behind one. Your own Docker images, kind cluster and registries
# are never touched, and no host ports are published.
#
#   mitm    proxysim-mitm, mitmproxy: the only container with a route out. It re-signs every
#           HTTPS connection with its own CA, as a corporate proxy does.
#   lan     proxysim-lan, a network with no route out. Everything under test runs on it,
#           with the proxy variables set.
#
# Three tests, each run with one cert mode, or all three when the mode is left out:
#   none    no CA given            expected: fails with a TLS/certificate error
#   wrong   a fresh, unrelated CA  expected: fails with a TLS/certificate error
#   right   mitmproxy's CA         expected: passes, and mitmproxy's log shows the requests
#
#   setup   builds .devcontainer/Dockerfile with that CA as proxy-ca.crt (from a copy of the
#           folder), then runs `mise trust --all && mise run setup` as vscode in the image,
#           on a copy of the working tree. The dev container's apt step uses plain http, so
#           with no CA the build fails at the mise download.
#   build   builds the nexus-api image (ALL=1: every image in the bake default group), with
#           that CA as the proxy_ca build secret. Build only: nothing is pushed or loaded.
#   pull    docker pull of a small image in a stock docker:dind (privileged) whose system
#           trust store has that CA.
#
# Both builds use proxysim-builder, a buildx builder (docker-container driver) on the lan.
# It stands for your own Docker after setup-proxy-ca.sh: it always trusts mitmproxy's CA,
# so base images pull, and the mode only changes what the build itself is given.
#
#   ./scripts/proxy-sim.sh up                         # start mitm and the lan (the tests do it too)
#   ./scripts/proxy-sim.sh setup [none|wrong|right]
#   ./scripts/proxy-sim.sh build [none|wrong|right]   # ALL=1 for every image
#   ./scripts/proxy-sim.sh pull [none|wrong|right]    # IMAGE=<image>, default ghcr.io/jqlang/jq:latest
#   ./scripts/proxy-sim.sh shell                      # a shell in the last setup test's container
#   ./scripts/proxy-sim.sh down                       # remove everything the simulation made
#
# Via mise: mise run proxy-sim-up, -setup, -build (--all), -pull (each with --mode), -shell, -down.
# `docker logs proxysim-mitm` shows what crossed the proxy. Exits non-zero when a result is
# not the expected one, and keeps that run's log.
####################################################################################

cd "$(dirname "$0")/.."

COMMAND="${1:-}"
MODE="${2:-}"
IMAGE="${IMAGE:-ghcr.io/jqlang/jq:latest}"

NETWORK="proxysim-lan"
SUBNET="10.77.0.0/24"
# A fixed address, not the container name: build steps run in their own network namespace,
# where Docker's DNS does not answer.
MITM_IP="10.77.0.2"
MITM="proxysim-mitm"
CA_VOLUME="proxysim-mitm-ca"
CA_FILE="/home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.pem"
BUILDER="proxysim-builder"
BUILDER_CONTAINER="buildx_buildkit_${BUILDER}0"
DIND="proxysim-dind"
DEV="proxysim-devcontainer"
PROXY_URL="http://${MITM_IP}:8080"
NO_PROXY_LIST="localhost,127.0.0.1"
PROXY_VARS=(
  "HTTP_PROXY=${PROXY_URL}" "HTTPS_PROXY=${PROXY_URL}" "NO_PROXY=${NO_PROXY_LIST}"
  "http_proxy=${PROXY_URL}" "https_proxy=${PROXY_URL}" "no_proxy=${NO_PROXY_LIST}"
)
# What a client prints when it does not trust the certificate it was shown.
TLS_ERRORS='x509:|failed to verify certificate|certificate verify failed|CERTIFICATE_VERIFY_FAILED|SSL certificate problem|unknown authority|invalid peer certificate|UnknownIssuer'

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

wait_for() {
  local what="$1"; shift
  for _ in $(seq 1 90); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "Timed out waiting for ${what}" >&2
  exit 1
}

up() {
  docker network inspect "$NETWORK" >/dev/null 2>&1 || \
    docker network create --internal --subnet "$SUBNET" "$NETWORK" >/dev/null
  if ! docker inspect "$MITM" >/dev/null 2>&1; then
    docker run -d --name "$MITM" -v "${CA_VOLUME}:/home/mitmproxy/.mitmproxy" \
      mitmproxy/mitmproxy mitmdump --listen-port 8080 --set block_global=false \
      --set stream_large_bodies=1m >/dev/null
    docker network connect --ip "$MITM_IP" "$NETWORK" "$MITM"
  fi
  wait_for "the mitm CA" docker exec "$MITM" test -f "$CA_FILE"
  docker cp -q "${MITM}:${CA_FILE}" "${WORK}/right.crt"
}

# The builder, on the lan, trusting mitmproxy's CA (see the header).
builder() {
  docker buildx inspect "$BUILDER" >/dev/null 2>&1 && return 0
  local opts=()
  # Quoted: --driver-opt is comma separated, and NO_PROXY has commas
  for v in "${PROXY_VARS[@]}"; do opts+=(--driver-opt "\"env.${v}\""); done
  docker buildx create --name "$BUILDER" --driver docker-container \
    --driver-opt "network=${NETWORK}" "${opts[@]}" >/dev/null
  docker buildx inspect --bootstrap "$BUILDER" >/dev/null
  docker cp -q "${WORK}/right.crt" "${BUILDER_CONTAINER}:/tmp/mitm.crt"
  docker exec "$BUILDER_CONTAINER" sh -c 'cat /tmp/mitm.crt >> /etc/ssl/certs/ca-certificates.crt'
  # buildkitd reads the trust store once, at start
  docker restart "$BUILDER_CONTAINER" >/dev/null
  docker buildx inspect --bootstrap "$BUILDER" >/dev/null
}

# Writes the mode's CA to $WORK/ca.crt: empty for none.
make_ca() {
  case "$1" in
    none)  : > "${WORK}/ca.crt" ;;
    wrong) openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=proxysim-wrong-ca \
             -addext basicConstraints=critical,CA:TRUE -keyout /dev/null -out "${WORK}/ca.crt" 2>/dev/null ;;
    right) cp "${WORK}/right.crt" "${WORK}/ca.crt" ;;
  esac
}

test_setup() {
  builder
  rm -rf "${WORK}/devcontainer"
  cp -r .devcontainer "${WORK}/devcontainer"
  cp "${WORK}/ca.crt" "${WORK}/devcontainer/proxy-ca.crt"
  local args=()
  for v in "${PROXY_VARS[@]}"; do args+=(--build-arg "$v"); done
  docker buildx build --builder "$BUILDER" --no-cache --progress plain "${args[@]}" \
    --load -t "${DEV}:latest" "${WORK}/devcontainer"
  docker rm -f "$DEV" >/dev/null 2>&1 || true
  # The proxy, and devcontainer.json's containerEnv minus the host paths
  local envs=()
  for v in "${PROXY_VARS[@]}"; do envs+=(-e "$v"); done
  docker run -d --name "$DEV" --network "$NETWORK" "${envs[@]}" \
    -e MISE_ENV=devcontainer \
    -e SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    -e REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    -e NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    -e PATH=/home/vscode/.local/share/mise/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    "${DEV}:latest" sleep infinity >/dev/null
  # The working tree, minus anything gitignored, so a run never writes into your checkout.
  docker exec -u vscode "$DEV" mkdir -p /home/vscode/fn
  git ls-files -z --cached --others --exclude-standard --deduplicate \
    | tar --null -T - --ignore-failed-read -cf - 2>/dev/null \
    | docker exec -i -u vscode "$DEV" tar -xf - -C /home/vscode/fn
  docker exec -u vscode -w /home/vscode/fn "$DEV" cp .dev.env.example .dev.env
  docker exec -u vscode -w /home/vscode/fn "$DEV" bash -c 'mise trust --all && mise run setup'
}

test_build() {
  local targets=(nexus-api-fn) secret=() args=()
  [ -z "${ALL:-}" ] || targets=(default)
  [ ! -s "${WORK}/ca.crt" ] || secret=(--set "*.secrets=id=proxy_ca,src=${WORK}/ca.crt")
  # BuildKit gives these to RUN steps without keeping them in the image.
  for v in "${PROXY_VARS[@]}"; do args+=(--set "*.args.${v}"); done
  builder
  docker buildx bake --builder "$BUILDER" --no-cache --progress plain -f docker-bake.hcl \
    "${args[@]}" ${secret[@]+"${secret[@]}"} --set '*.output=type=cacheonly' "${targets[@]}"
}

test_pull() {
  local envs=() rc=0
  for v in "${PROXY_VARS[@]}"; do envs+=(-e "$v"); done
  docker rm -f "$DIND" >/dev/null 2>&1 || true
  # The CA goes in the system trust store before dockerd starts, as IT pushes it to a laptop.
  docker run -d --rm --privileged --name "$DIND" --network "$NETWORK" "${envs[@]}" \
    -e DOCKER_TLS_CERTDIR= -v "${WORK}/ca.crt:/proxysim-ca.crt:ro" --entrypoint sh docker:dind \
    -c 'cat /proxysim-ca.crt >> /etc/ssl/certs/ca-certificates.crt; exec dockerd-entrypoint.sh' >/dev/null
  wait_for "the dind daemon" docker exec "$DIND" docker info
  docker exec "$DIND" docker pull "$IMAGE" || rc=$?
  docker rm -f "$DIND" >/dev/null 2>&1 || true
  return "$rc"
}

# Runs one test in one mode and checks the result against the expected one.
run() {
  local test="$1" mode="$2" log="${WORK}/${1}-${2}.log" start rc mitm_log kept
  make_ca "$mode"
  echo "=== ${test}, ${mode} cert ==="
  start="$(date +%s)"
  # The test stops at its first failing step (set -e in the subshell).
  set +e
  (set -e; "test_${test}") 2>&1 | tee "$log"
  rc="${PIPESTATUS[0]}"
  set -e
  sleep 1
  mitm_log="$(docker logs --since "$start" "$MITM" 2>&1)"
  if [ "$mode" = right ]; then
    if [ "$rc" -eq 0 ] && grep -q 'https://' <<<"$mitm_log"; then
      RESULTS+=("PASS   ${test} ${mode}: passed, through the proxy"); return 0
    elif [ "$rc" -eq 0 ]; then
      RESULTS+=("FAIL   ${test} ${mode}: passed, but mitmproxy logged no requests")
    else
      RESULTS+=("FAIL   ${test} ${mode}: failed (exit ${rc}), expected to pass")
    fi
  else
    if [ "$rc" -ne 0 ] && grep -q -E "$TLS_ERRORS" "$log"; then
      RESULTS+=("PASS   ${test} ${mode}: failed with a TLS error, as expected"); return 0
    elif [ "$rc" -eq 0 ]; then
      RESULTS+=("FAIL   ${test} ${mode}: passed, expected a TLS error")
    else
      RESULTS+=("ERROR  ${test} ${mode}: failed (exit ${rc}), but not with a TLS error")
    fi
  fi
  # Keep the log of a bad result: $WORK goes on exit.
  kept="$(mktemp "${TMPDIR:-/tmp}/proxysim-${test}-${mode}-XXXX.log")"
  cp "$log" "$kept"
  RESULTS[-1]+=" (log: ${kept})"
  FAILED=1
}

case "$COMMAND" in
  up)
    up
    echo "Up: ${MITM} at ${PROXY_URL} on ${NETWORK}. Try: $0 pull"
    ;;

  setup|build|pull)
    case "$MODE" in
      "") modes=(none wrong right) ;;
      none|wrong|right) modes=("$MODE") ;;
      *) echo "Mode is none, wrong or right" >&2; exit 1 ;;
    esac
    up
    RESULTS=()
    FAILED=0
    for m in "${modes[@]}"; do run "$COMMAND" "$m"; done
    echo
    printf '%s\n' "${RESULTS[@]}"
    exit "$FAILED"
    ;;

  shell)
    docker exec -it -u vscode -w /home/vscode/fn "$DEV" bash
    ;;

  down)
    docker rm -f "$DEV" "$DIND" "$MITM" >/dev/null 2>&1 || true
    docker buildx rm "$BUILDER" >/dev/null 2>&1 || true
    docker image rm "${DEV}:latest" >/dev/null 2>&1 || true
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
    docker volume rm "$CA_VOLUME" >/dev/null 2>&1 || true
    echo "Removed."
    ;;

  *)
    echo "Usage: $0 <up|setup [mode]|build [mode]|pull [mode]|shell|down>, mode none|wrong|right"
    exit 1
    ;;
esac
