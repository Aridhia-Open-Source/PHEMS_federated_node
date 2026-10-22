#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Federated Node - one-step development install
#
# From a fresh clone on Debian 13 / Ubuntu 24.04 or later (fncli needs Python 3.12):
#
#   ./scripts/install-dev.sh          # or: make dev-install
#
# Docker is the one prerequisite: `docker info` must work without sudo. Everything
# else is installed here: apt packages (sudo), kind, kubectl, helm and tilt into
# ~/.local/bin, fncli with pipx (editable), direnv for .envrc. Then the config
# files, the kind cluster, the Helm release and Tilt, and a healthcheck at the end.
#
# Safe to rerun: every step checks first and skips what is already done. A release
# that is already deployed is left alone; a failed one is upgraded.
#
# Output also goes to ~/.fn/install.log, Tilt's to ~/.fn/tilt.log.
####################################################################################

cd "$(dirname "$0")/.."

# kind v0.31.0 rejects the registry mirror patches in .kind/kind-config.yaml, so pin
# v0.30.0 (same as scripts/proxy-sim/Dockerfile).
KIND_VERSION=v0.30.0
HELM_VERSION=v3.19.0
TILT_VERSION=0.37.5
APT_PACKAGES=(ca-certificates curl git make jq openssl python3 python3-venv pipx direnv)
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-1200}"

FN_DIR="$HOME/.fn"
BIN="$HOME/.local/bin"
mkdir -p "$FN_DIR" "$BIN"
export PATH="$BIN:$PATH"
# A login shell sets this; docker exec does not, and deploy_owner.sh needs it.
export USER="${USER:-$(id -un)}"

exec > >(tee -a "$FN_DIR/install.log") 2>&1

STEPS=9
N=0
step() { N=$((N + 1)); echo; echo "=== [$N/$STEPS] $1 $(printf '=%.0s' $(seq 1 $((60 - ${#1}))))"; }
ok()   { echo "  ok    $*"; }
skip() { echo "  skip  $*"; }
die()  { echo "  FAIL  $*" >&2; exit 1; }

echo "Federated Node dev install, $(date '+%F %T'). Log: $FN_DIR/install.log"

###############################################################################
step "Checking prerequisites"
###############################################################################
[ "$(id -u)" -ne 0 ] || die "run as your normal user, not root (sudo is used for apt only)"
# shellcheck source=/dev/null
. /etc/os-release
[[ " ${ID:-} ${ID_LIKE:-} " == *" debian "* ]] || die "Debian-based systems only (found ${PRETTY_NAME:-unknown})"
ok "$PRETTY_NAME"
command -v docker > /dev/null || die "Docker is not installed: https://docs.docker.com/engine/install/"
docker info > /dev/null 2>&1 || die "Docker is installed but \`docker info\` fails. Start it, and add yourself to the docker group (log out and back in after)."
ok "docker $(docker version --format '{{.Server.Version}}')"
case "$(dpkg --print-architecture)" in
  amd64) ARCH=amd64; TILT_ARCH=x86_64 ;;
  arm64) ARCH=arm64; TILT_ARCH=arm64 ;;
  *) die "unsupported architecture $(dpkg --print-architecture)" ;;
esac

###############################################################################
step "System packages (apt)"
###############################################################################
missing=()
for pkg in "${APT_PACKAGES[@]}"; do
  dpkg-query -W -f='${Status}' "$pkg" 2> /dev/null | grep -q "install ok installed" || missing+=("$pkg")
done
if [ "${#missing[@]}" -eq 0 ]; then
  skip "all installed: ${APT_PACKAGES[*]}"
else
  echo "  installing: ${missing[*]}"
  sudo apt-get update -q
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${missing[@]}"
  ok "installed ${missing[*]}"
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
  || die "fncli needs Python 3.12+, this system has $(python3 --version). Use Debian 13 or Ubuntu 24.04 and later."
ok "$(python3 --version)"

###############################################################################
step "Kubernetes tools (~/.local/bin)"
###############################################################################
if kind version 2> /dev/null | grep -q "kind $KIND_VERSION "; then
  skip "kind $KIND_VERSION"
else
  curl -fsSLo "$BIN/kind" "https://kind.sigs.k8s.io/dl/$KIND_VERSION/kind-linux-$ARCH"
  chmod +x "$BIN/kind"
  ok "kind $KIND_VERSION"
fi

if command -v kubectl > /dev/null; then
  skip "kubectl $(kubectl version --client -o json | jq -r .clientVersion.gitVersion)"
else
  curl -fsSLo "$BIN/kubectl" "https://dl.k8s.io/release/$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/$ARCH/kubectl"
  chmod +x "$BIN/kubectl"
  ok "kubectl $(kubectl version --client -o json | jq -r .clientVersion.gitVersion)"
fi

if helm version --short 2> /dev/null | grep -q '^v3\.'; then
  skip "helm $(helm version --short)"
else
  curl -fsSL "https://get.helm.sh/helm-$HELM_VERSION-linux-$ARCH.tar.gz" \
    | tar -xz -C "$BIN" --strip-components=1 "linux-$ARCH/helm"
  ok "helm $HELM_VERSION"
fi

if command -v tilt > /dev/null; then
  skip "tilt $(tilt version)"
else
  curl -fsSL "https://github.com/tilt-dev/tilt/releases/download/v$TILT_VERSION/tilt.$TILT_VERSION.linux.$TILT_ARCH.tar.gz" \
    | tar -xz -C "$BIN" tilt
  ok "tilt $TILT_VERSION"
fi

###############################################################################
step "fncli and direnv"
###############################################################################
if pipx list --short 2> /dev/null | grep -q '^phems '; then
  skip "fncli (pipx package phems; reinstall: pipx install --force --editable './dagster[cli]')"
else
  pipx install --editable './dagster[cli]'
  ok "fncli"
fi
pipx ensurepath > /dev/null 2>&1 || true

# Hook direnv into bash so .envrc loads .dev.env on cd into the repo.
if grep -qs 'direnv hook bash' "$HOME/.bashrc"; then
  skip "direnv hook in ~/.bashrc"
else
  printf '\neval "$(direnv hook bash)"\n' >> "$HOME/.bashrc"
  ok "direnv hook added to ~/.bashrc (new shells)"
fi
direnv allow . && ok "direnv allowed for $(pwd)"

###############################################################################
step "Config files"
###############################################################################
if [ -f .dev.env ]; then
  skip ".dev.env exists"
else
  cp .dev.env.example .dev.env
  ok ".dev.env from .dev.env.example"
fi
if [ -f k8s/federated-node/dev.values.yaml ]; then
  skip "k8s/federated-node/dev.values.yaml exists"
else
  cp k8s/federated-node/dev.example.values.yml k8s/federated-node/dev.values.yaml
  ok "k8s/federated-node/dev.values.yaml from dev.example.values.yml"
fi
# fncli demo's own names (MANAGEMENT.md).
if [ -f .demo.env ]; then
  skip ".demo.env exists"
else
  cp .demo.env.example .demo.env
  ok ".demo.env from .demo.env.example"
fi
# shellcheck source=/dev/null
source .dev.env
if [ -z "${KEYCLOAK_FIRST_USER_EMAIL:-}" ]; then
  sed -i 's/^KEYCLOAK_FIRST_USER_EMAIL=.*/KEYCLOAK_FIRST_USER_EMAIL=admin@example.com/' .dev.env
  ok "first user email: admin@example.com"
fi
if [ -z "${KEYCLOAK_FIRST_USER_PASSWORD:-}" ]; then
  sed -i "s/^KEYCLOAK_FIRST_USER_PASSWORD=.*/KEYCLOAK_FIRST_USER_PASSWORD=Fn1-$(openssl rand -hex 8)/" .dev.env
  ok "first user password generated (in .dev.env)"
fi
# shellcheck source=/dev/null
source .dev.env

###############################################################################
step "Helm chart dependencies"
###############################################################################
make helm_deps
ok "subcharts in k8s/federated-node/charts"

###############################################################################
step "kind cluster and registries"
###############################################################################
make cluster up
ok "cluster kind-$CLUSTER_NAME"

###############################################################################
step "Helm release"
###############################################################################
status="$(helm status "$RELEASE_NAME" -n "$NAMESPACE" --kube-context "kind-$CLUSTER_NAME" -o json 2> /dev/null | jq -r .info.status || true)"
case "$status" in
  "")       make deploy;  ok "release $RELEASE_NAME installed" ;;
  deployed) skip "release $RELEASE_NAME already deployed (redeploy: make upgrade)" ;;
  *)        echo "  release $RELEASE_NAME is '$status', upgrading"; make upgrade; ok "release $RELEASE_NAME upgraded" ;;
esac

###############################################################################
step "Tilt"
###############################################################################
if curl -s -o /dev/null -m 5 http://localhost:10350/; then
  skip "Tilt already running"
else
  pkill -x tilt || true # a Tilt left over from before a redeploy keeps stale port-forwards
  sleep 2
  setsid nohup tilt up --stream > "$FN_DIR/tilt.log" 2>&1 < /dev/null &
  ok "Tilt started in the background (log: $FN_DIR/tilt.log, stop: make tilt-down)"
fi

###############################################################################
step "Healthcheck"
###############################################################################
NAMES=("Tilt dashboard" "Backend API" "Dagster UI" "Gitea" "Keycloak" "Postgres")
URLS=(
  http://localhost:10350/
  http://localhost:5000/health_check
  http://localhost:3000/server_info
  http://localhost:4000/api/healthz
  http://localhost:8080/
  localhost:5432
)

is_up() {
  case "$1" in
    http*) [[ "$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$1")" =~ ^[234] ]] ;;
    *) timeout 3 bash -c "</dev/tcp/${1%:*}/${1#*:}" 2> /dev/null ;;
  esac
}

echo "  waiting up to $((HEALTH_TIMEOUT / 60)) min for every service"
declare -A UP=()
start=$SECONDS
while [ "${#UP[@]}" -lt "${#NAMES[@]}" ] && [ $((SECONDS - start)) -lt "$HEALTH_TIMEOUT" ]; do
  for i in "${!NAMES[@]}"; do
    [ -n "${UP[$i]:-}" ] && continue
    if is_up "${URLS[$i]}"; then
      UP[$i]=1
      ok "${NAMES[$i]} after $((SECONDS - start))s"
    fi
  done
  [ "${#UP[@]}" -lt "${#NAMES[@]}" ] && sleep 5
done

echo
printf '  %-16s %-38s %s\n' SERVICE ADDRESS STATUS
for i in "${!NAMES[@]}"; do
  printf '  %-16s %-38s %s\n' "${NAMES[$i]}" "${URLS[$i]}" "$([ -n "${UP[$i]:-}" ] && echo up || echo DOWN)"
done
echo
echo "  API login: $KEYCLOAK_FIRST_USER_EMAIL / $KEYCLOAK_FIRST_USER_PASSWORD (from .dev.env)"
echo "  Next: fncli demo (see MANAGEMENT.md). Open a new shell first so PATH and direnv load."

[ "${#UP[@]}" -eq "${#NAMES[@]}" ] || die "not everything came up. Check: tilt logs, kubectl get pods -A, $FN_DIR/tilt.log"
echo
echo "=== All up ==="
