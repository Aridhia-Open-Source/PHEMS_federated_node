#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Federated Node - proxy CA setup
#
# For a machine behind a TLS-intercepting proxy, or one that must trust a private CA:
# trust the CA, point Docker and this repo's tooling at the proxy, then check it works.
# Guide: PROXY_CA_SETUP.md
#
#   ./scripts/setup-proxy-ca.sh --ca-file PATH [--proxy URL] [--yes] [--dry-run]
#   ./scripts/setup-proxy-ca.sh --undo [--yes] [--dry-run]
#
#   --ca-file PATH  the CA as a PEM file (one certificate or a bundle); or set CUSTOM_CA_FILE
#   --proxy URL     for example http://proxy.example.org:8080; defaults to HTTPS_PROXY
#                   if set. Without one, only the CA is set up.
#   --yes           do not ask
#   --dry-run       show every change and make none
#   --undo          remove what a previous run added
#
# Each step is skipped if it is already done: the CA in the system trust store, a Docker
# daemon proxy drop-in (systemd only; Docker restarts, which stops running containers), the
# Docker client proxy in ~/.docker/config.json (image builds and containers you start), and
# a managed block in .dev.env with CUSTOM_CA_FILE and the proxy and CA-bundle variables.
####################################################################################

cd "$(dirname "$0")/.."

CA_FILE="${CUSTOM_CA_FILE:-}"
PROXY="${HTTPS_PROXY:-${https_proxy:-}}"
YES=0
DRY=0
UNDO=0

START="# >>> setup-proxy-ca >>>"
END="# <<< setup-proxy-ca <<<"
DOCKER_DROPIN=/etc/systemd/system/docker.service.d/http-proxy.conf
DOCKER_CONFIG_FILE="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
LOCAL_NO_PROXY="localhost,127.0.0.1,kind-registry,proxy-docker-hub-registry,proxy-ghcr-registry"

ok()   { printf '  [%s]   %s\n' "$([ "$DRY" = 1 ] && echo dry || echo ok)" "$*"; }
skip() { printf '  [skip] %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*" >&2; }
die()  { printf '  [FAIL] %s\n' "$*" >&2; exit 1; }
usage() { sed -n '5,22p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --ca-file) CA_FILE="${2:?--ca-file needs a path}"; shift 2 ;;
    --proxy) PROXY="${2:?--proxy needs a URL}"; shift 2 ;;
    --yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --undo) UNDO=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"

# Runs a command, or only prints it with --dry-run.
run() {
  if [ "$DRY" = 1 ]; then printf '  would run: %s\n' "$*"; else "$@"; fi
}

confirm() {
  if [ "$YES" = 1 ] || [ "$DRY" = 1 ]; then return 0; fi
  [ -t 0 ] || die "no terminal to ask on: run again with --yes"
  local answer
  read -r -p "  $1 [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]]
}

if command -v update-ca-certificates >/dev/null; then
  TRUST_DIR=/usr/local/share/ca-certificates
  TRUST_CMD=update-ca-certificates
  BUNDLE=/etc/ssl/certs/ca-certificates.crt
elif command -v update-ca-trust >/dev/null; then
  TRUST_DIR=/etc/pki/ca-trust/source/anchors
  TRUST_CMD=update-ca-trust
  BUNDLE=/etc/pki/tls/certs/ca-bundle.crt
else
  die "found neither update-ca-certificates nor update-ca-trust: install the ca-certificates package"
fi
TRUST_FILE="$TRUST_DIR/fn-proxy-ca.crt"

NO_PROXY_ALL="$(printf '%s' "$LOCAL_NO_PROXY${NO_PROXY:+,$NO_PROXY}" | tr ',' '\n' | awk 'NF && !seen[$0]++' | paste -sd,)"

restart_docker() {
  echo "  Docker has to restart to use this, and that stops every running container, including a kind cluster."
  if confirm "Restart Docker now?"; then
    run $SUDO systemctl restart docker
    ok "Docker restarted"
  else
    DOCKER_PENDING=1
    warn "restart it yourself when ready: sudo systemctl restart docker"
  fi
}

has_docker_service() {
  [ -d /run/systemd/system ] && systemctl cat docker.service >/dev/null 2>&1
}

env_block() {
  echo "$START managed by scripts/setup-proxy-ca.sh, remove with --undo"
  echo "export CUSTOM_CA_FILE=$TRUST_FILE"
  for v in SSL_CERT_FILE REQUESTS_CA_BUNDLE CURL_CA_BUNDLE GIT_SSL_CAINFO PIP_CERT; do
    echo "export $v=$BUNDLE"
  done
  if [ -n "$PROXY" ]; then
    for v in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy; do echo "export $v=$PROXY"; done
    for v in NO_PROXY no_proxy; do echo "export $v=$NO_PROXY_ALL"; done
  fi
  echo "$END"
}

drop_block() {
  sed "\|^$START|,\|^$END|d" .dev.env
}

###############################################################################
# UNDO
###############################################################################
if [ "$UNDO" = 1 ]; then
  echo "Undoing the proxy CA setup"
  if [ -f "$TRUST_FILE" ]; then
    run $SUDO rm -f "$TRUST_FILE"
    run $SUDO $TRUST_CMD --fresh >/dev/null 2>&1 || run $SUDO $TRUST_CMD >/dev/null
    ok "CA removed from the system trust store"
  else
    skip "no CA from this script in the system trust store"
  fi
  if [ -f "$DOCKER_DROPIN" ]; then
    run $SUDO rm -f "$DOCKER_DROPIN"
    run $SUDO systemctl daemon-reload
    ok "Docker proxy drop-in removed"
    DOCKER_PENDING=0
    restart_docker
  else
    skip "no Docker proxy drop-in"
  fi
  if command -v jq >/dev/null && [ -n "$(jq -c '.proxies.default // empty' "$DOCKER_CONFIG_FILE" 2>/dev/null)" ]; then
    if [ "$DRY" = 1 ]; then echo "  would remove proxies.default from $DOCKER_CONFIG_FILE"
    else tmp="$(mktemp)"; jq 'del(.proxies.default)' "$DOCKER_CONFIG_FILE" > "$tmp" && cat "$tmp" > "$DOCKER_CONFIG_FILE"; rm -f "$tmp"; fi
    ok "proxies.default removed from $DOCKER_CONFIG_FILE"
  else
    skip "no Docker client proxy in $DOCKER_CONFIG_FILE"
  fi
  if [ -f .dev.env ] && grep -q "^$START" .dev.env; then
    if [ "$DRY" = 1 ]; then echo "  would remove the setup-proxy-ca block from .dev.env"
    else tmp="$(mktemp)"; drop_block > "$tmp"; cat "$tmp" > .dev.env; rm -f "$tmp"; fi
    ok "block removed from .dev.env"
  else
    skip "no setup-proxy-ca block in .dev.env"
  fi
  exit 0
fi

###############################################################################
# CHECK THE CA
###############################################################################
[ -n "$CA_FILE" ] || { usage >&2; die "give the CA with --ca-file PATH (a PEM file from your IT team)"; }
[ -s "$CA_FILE" ] || die "$CA_FILE is missing or empty"
grep -q -e '-----BEGIN CERTIFICATE-----' "$CA_FILE" \
  || die "$CA_FILE is not a PEM certificate: it should start with -----BEGIN CERTIFICATE-----. For a .cer or .der file: openssl x509 -inform der -in file.cer -out ca.pem"
command -v openssl >/dev/null || die "openssl is needed to check the CA: install it first"
CA_FILE="$(cd "$(dirname "$CA_FILE")" && pwd)/$(basename "$CA_FILE")"
openssl x509 -in "$CA_FILE" -noout >/dev/null 2>&1 || die "openssl cannot read $CA_FILE"
openssl x509 -in "$CA_FILE" -noout -checkend 0 >/dev/null || die "this CA has expired: ask IT for the current one"

echo "The CA to trust (the first certificate in $CA_FILE):"
openssl x509 -in "$CA_FILE" -noout -subject -issuer -enddate -fingerprint -sha256 | sed 's/^/  /'
if ! openssl x509 -in "$CA_FILE" -noout -text | grep -q "CA:TRUE"; then
  warn "this does not look like a CA certificate (no CA:TRUE). A server certificate will not make the proxy's connections verify: ask IT for the root or issuing CA."
fi
echo
[ -z "$PROXY" ] && warn "no proxy given: only the CA is set up. Add --proxy URL if you are behind one."
confirm "Trust this CA on this machine?" || die "stopped, nothing changed"

DOCKER_PENDING=0

###############################################################################
# 1. System trust store
###############################################################################
echo "1. System trust store"
if [ -f "$TRUST_FILE" ] && cmp -s "$CA_FILE" "$TRUST_FILE"; then
  skip "CA already trusted"
else
  run $SUDO install -m 0644 "$CA_FILE" "$TRUST_FILE"
  if [ "$DRY" = 1 ]; then echo "  would run: $SUDO $TRUST_CMD"; else $SUDO $TRUST_CMD >/dev/null; fi
  ok "CA added ($TRUST_FILE)"
fi

###############################################################################
# 2. Docker daemon proxy
###############################################################################
echo "2. Docker daemon proxy"
if [ -z "$PROXY" ]; then
  skip "no proxy given"
elif ! has_docker_service; then
  warn "Docker is not a systemd service here (Docker Desktop, rootless or a container). Set the proxy in Docker yourself: HTTPS_PROXY=$PROXY NO_PROXY=$NO_PROXY_ALL, then restart Docker."
else
  want="$(printf '[Service]\nEnvironment="HTTP_PROXY=%s"\nEnvironment="HTTPS_PROXY=%s"\nEnvironment="NO_PROXY=%s"' "$PROXY" "$PROXY" "$NO_PROXY_ALL")"
  if [ -f "$DOCKER_DROPIN" ] && [ "$($SUDO cat "$DOCKER_DROPIN")" = "$want" ]; then
    skip "drop-in already set"
  else
    [ ! -f "$DOCKER_DROPIN" ] || run $SUDO cp -a "$DOCKER_DROPIN" "$DOCKER_DROPIN.bak"
    run $SUDO mkdir -p "$(dirname "$DOCKER_DROPIN")"
    if [ "$DRY" = 1 ]; then echo "  would write $DOCKER_DROPIN:"; echo "$want" | sed 's/^/    /'
    else printf '%s\n' "$want" | $SUDO tee "$DOCKER_DROPIN" >/dev/null; fi
    run $SUDO systemctl daemon-reload
    ok "drop-in written ($DOCKER_DROPIN)"
    restart_docker
  fi
fi

###############################################################################
# 3. Docker client proxy: gives every docker build and docker run the proxy variables
###############################################################################
echo "3. Docker client proxy (image builds, and containers you start)"
if [ -z "$PROXY" ]; then
  skip "no proxy given"
elif ! command -v jq >/dev/null; then
  warn "jq is not installed. Add this to $DOCKER_CONFIG_FILE yourself: {\"proxies\": {\"default\": {\"httpProxy\": \"$PROXY\", \"httpsProxy\": \"$PROXY\", \"noProxy\": \"$NO_PROXY_ALL\"}}}"
else
  want="$(jq -nc --arg p "$PROXY" --arg n "$NO_PROXY_ALL" '{httpProxy: $p, httpsProxy: $p, noProxy: $n}')"
  have="$(jq -c '.proxies.default // empty' "$DOCKER_CONFIG_FILE" 2>/dev/null || true)"
  if [ "$have" = "$want" ]; then
    skip "already set"
  elif [ "$DRY" = 1 ]; then
    echo "  would set proxies.default in $DOCKER_CONFIG_FILE to: $want"
  else
    mkdir -p "$(dirname "$DOCKER_CONFIG_FILE")"
    [ -f "$DOCKER_CONFIG_FILE" ] || echo '{}' > "$DOCKER_CONFIG_FILE"
    tmp="$(mktemp)"
    jq --argjson p "$want" '.proxies.default = $p' "$DOCKER_CONFIG_FILE" > "$tmp" && cat "$tmp" > "$DOCKER_CONFIG_FILE"
    rm -f "$tmp"
    ok "proxies.default set in $DOCKER_CONFIG_FILE"
  fi
fi

###############################################################################
# 4. .dev.env
###############################################################################
echo "4. .dev.env"
if [ ! -f .dev.env ]; then
  [ -f .dev.env.example ] || die "run this from a checkout of the repo (no .dev.env.example here)"
  run cp .dev.env.example .dev.env
  ok ".dev.env created from .dev.env.example (set KEYCLOAK_FIRST_USER_EMAIL and KEYCLOAK_FIRST_USER_PASSWORD in it)"
fi
if [ -f .dev.env ] && [ "$(sed -n "\|^$START|,\|^$END|p" .dev.env)" = "$(env_block)" ]; then
  skip "block already there"
elif [ "$DRY" = 1 ]; then
  echo "  would add to .dev.env:"; env_block | sed 's/^/    /'
else
  tmp="$(mktemp)"
  drop_block > "$tmp"
  env_block >> "$tmp"
  cat "$tmp" > .dev.env
  rm -f "$tmp"
  ok "block written to .dev.env"
fi

###############################################################################
# 5. Check it works
###############################################################################
echo "5. Check"
if [ "$DRY" = 1 ]; then
  echo "  would check https://ghcr.io with the new trust, and a docker pull"
  exit 0
fi
failed=0
check_env=(env)
[ -z "$PROXY" ] || check_env+=("HTTPS_PROXY=$PROXY" "NO_PROXY=$NO_PROXY_ALL")
if err="$("${check_env[@]}" curl -sS -o /dev/null -I -m 20 https://ghcr.io 2>&1)"; then
  ok "https://ghcr.io verifies${PROXY:+ through the proxy}"
else
  failed=1
  echo "  [FAIL] https://ghcr.io: $err" >&2
  case "$err" in
    *"unable to get local issuer"*|*"self-signed"*|*"certificate"*) echo "         The CA does not match the proxy's certificates, or an intermediate is missing. Ask IT for the full chain." >&2 ;;
    *"Could not resolve"*|*"proxy"*|*"Connection refused"*|*"timed out"*) echo "         Check the proxy address, and that this machine can reach it." >&2 ;;
  esac
fi
if [ "$DOCKER_PENDING" = 1 ]; then
  skip "docker pull: restart Docker first, then run this script again"
elif docker info >/dev/null 2>&1; then
  if docker pull -q ghcr.io/jqlang/jq:latest >/dev/null 2>&1; then
    ok "docker pull works"
  else
    failed=1
    echo "  [FAIL] docker pull ghcr.io/jqlang/jq:latest. Try it yourself for the error; then see PROXY_CA_SETUP.md" >&2
  fi
else
  skip "docker pull: Docker is not running or not usable without sudo"
fi
echo
if [ "$failed" = 1 ]; then
  die "setup finished but a check failed: see PROXY_CA_SETUP.md, 'If something fails'"
fi
echo "Done. Open a new shell (or run: direnv allow) so the variables in .dev.env load."
echo "Next: ./scripts/install-dev.sh, or make cluster up."
echo "Image builds get the CA as a build secret (needs BuildKit, Docker 23 or later)."
echo "Known gap: the registry mirrors that make cluster up starts do not get the CA yet."
