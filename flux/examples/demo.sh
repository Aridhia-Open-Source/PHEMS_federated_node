#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Reproducible Flux/Gitea demo.
#
# By default this script creates the two visible Gitea pull requests and pauses
# for a human to merge each one. Pass --auto-merge for an unattended demo.
###############################################################################

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

AUTO_MERGE=0
CHART_VERSION="${FLUX_DEMO_CHART_VERSION:-0.0.1-dev}"
SITE_REPO="${SITE_REPO:-fn-site}"
SITE_DIR=".local/$SITE_REPO"
SITE_BRANCH="${SITE_BRANCH:-demo-install}"
RESOURCES_BRANCH="${RESOURCES_BRANCH:-bootstrap-demo-resources}"
GITEA_LOCAL_URL="${GITEA_LOCAL_URL:-http://localhost:4000}"
HR_NAME=federated-node
PIDS=()

usage() {
  cat <<'EOF'
Usage: flux/examples/demo.sh [--auto-merge]

Creates the complete local Flux demo:
  - kind cluster and local chart image
  - external Docker Gitea and Actions runner
  - Flux GitRepository/Kustomization
  - installation PR for the site repository
  - project/resources PR for the demo repositories
  - experiment database and seed data
  - Dagster sensors and a merged demo trigger PR

Without --auto-merge, stop at each PR and merge it in Gitea before continuing.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --auto-merge) AUTO_MERGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

source scripts/load_env.sh
source scripts/gitea_lib.sh

if [ -x "$ROOT/.venv/bin/fncli" ]; then
  FNCLI="$ROOT/.venv/bin/fncli"
else
  FNCLI="$(command -v fncli || true)"
fi
[ -n "$FNCLI" ] || { echo "fncli is not installed; run mise run setup first" >&2; exit 1; }

cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

json_body() {
  python3 - "$@" <<'PY'
import json
import sys

print(json.dumps(dict(zip(sys.argv[1::2], sys.argv[2::2]))))
PY
}

pr_url() {
  echo "$GITEA_URL/$GITEA_ADMIN_USER/$SITE_REPO/pulls/$1"
}

open_or_update_pr() {
  local branch="$1" title="$2" body="$3" response number
  response="$(gitea_api GET "/repos/$GITEA_ADMIN_USER/$SITE_REPO/pulls?state=open&base=main&head=$GITEA_ADMIN_USER:$branch")"
  number="$(printf '%s' "$response" | python3 -c 'import json, sys; data=json.load(sys.stdin); print(data[0]["number"] if data else "")')"
  if [ -z "$number" ]; then
    response="$(gitea_api POST "/repos/$GITEA_ADMIN_USER/$SITE_REPO/pulls" \
      -d "$(json_body title "$title" body "$body" head "$branch" base main)")"
    number="$(printf '%s' "$response" | python3 -c 'import json, sys; print(json.load(sys.stdin)["number"])')"
  fi
  echo "$number"
}

is_merged() {
  local number="$1"
  gitea_api GET "/repos/$GITEA_ADMIN_USER/$SITE_REPO/pulls/$number" |
    python3 -c 'import json, sys; value=json.load(sys.stdin); print("yes" if value.get("merged") else "no")'
}

merge_pr() {
  local number="$1"
  gitea_api POST "/repos/$GITEA_ADMIN_USER/$SITE_REPO/pulls/$number/merge" \
    -d '{"Do":"merge","MergeMessageField":"Merge pull request"}' >/dev/null
}

wait_for_merge() {
  local number="$1" message="$2"
  echo "$message"
  if [ "$AUTO_MERGE" = 1 ]; then
    merge_pr "$number"
  elif [ ! -t 0 ]; then
    echo "No terminal is available to wait for a manual merge; rerun with --auto-merge." >&2
    exit 1
  else
    read -r -p "Merge $GITEA_URL/$GITEA_ADMIN_USER/$SITE_REPO/pulls/$number, then press Enter: "
  fi
  for _ in $(seq 60); do
    [ "$(is_merged "$number")" = yes ] && return
    sleep 5
  done
  echo "Timed out waiting for PR #$number to merge" >&2
  exit 1
}

start_forward() {
  local namespace="$1" service="$2" local_port="$3" service_port="$4" url="$5"
  curl -fsS --max-time 2 "$url" >/dev/null 2>&1 && return
  kubectl port-forward -n "$namespace" "svc/$service" "$local_port:$service_port" >/tmp/fn-flux-demo-"$local_port".log 2>&1 &
  PIDS+=("$!")
  for _ in $(seq 30); do
    curl -fsS --max-time 2 "$url" >/dev/null 2>&1 && return
    sleep 1
  done
  cat /tmp/fn-flux-demo-"$local_port".log >&2 || true
  echo "Timed out starting port-forward for $service" >&2
  exit 1
}

wait_for_fn_resources() {
  local expected="$1"
  for _ in $(seq 90); do
    if kubectl get gitproviders,nodesecrets,repositories,projects -n fn-operator -o json |
      EXPECTED="$expected" python3 -c '
import json, os, sys
expected = set(os.environ["EXPECTED"].split())
items = json.load(sys.stdin)["items"]
found = {item["metadata"]["name"] for item in items if item.get("status", {}).get("synced") is True}
raise SystemExit(0 if expected <= found else 1)
'; then
      return
    fi
    sleep 2
  done
  kubectl get gitproviders,nodesecrets,repositories,projects -n fn-operator -o wide
  echo "Timed out waiting for demo resources to sync" >&2
  exit 1
}

echo "== Preparing kind, chart dependencies and images"
mise run cluster up
mise run helm deps
mise run images

echo "== Starting external Gitea and Actions runner"
mise run gitea-bootstrap
gitea_connect

echo "== Publishing the chart and installing Flux"
mise run flux publish "$CHART_VERSION"
mise run flux up

echo "== Creating the installation pull request"
install_pr="$(open_or_update_pr "$SITE_BRANCH" \
  "Site: install Federated Node through Flux" \
  "Install the Federated Node from the Flux-managed site repository.")"
echo "Installation PR: $(pr_url "$install_pr")"
wait_for_merge "$install_pr" "Flux will install the application after this PR merges."
flux reconcile source git "$SITE_REPO" -n flux-system
flux reconcile kustomization "$SITE_REPO" -n flux-system --with-source
kubectl wait helmrelease/"$HR_NAME" -n "$NAMESPACE" --for=condition=Ready --timeout=30m

echo "== Starting local API, Dagster and Keycloak port-forwards"
start_forward fn nexus-api 5000 5000 http://localhost:5000/health_check
start_forward fn fn-dev-dagster-webserver 3000 80 http://localhost:3000
start_forward keycloak keycloak 8080 80 http://localhost:8080

echo "== Deploying and seeding the demo database"
export GITEA_LOCAL_URL
"$FNCLI" experiment deploy
"$FNCLI" experiment seed demo
kubectl create secret generic gitea-admin -n fn \
  --from-literal=password="$GITEA_ADMIN_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "== Preparing the project/resources pull request"
if [ -n "$(git -C "$SITE_DIR" status --short)" ]; then
  echo "$SITE_DIR has uncommitted changes; refusing to overwrite it" >&2
  exit 1
fi
git -C "$SITE_DIR" fetch -q origin main
git -C "$SITE_DIR" checkout -q -B "$RESOURCES_BRANCH" origin/main
mkdir -p "$SITE_DIR/node-config"
cp flux/examples/site/node-config/*.yaml "$SITE_DIR/node-config/"
python3 - "$SITE_DIR/kustomization.yaml" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if "  - node-config\n" not in text:
    text = text.replace("  - secrets/sops\n", "  - secrets/sops\n  - node-config\n")
path.write_text(text, encoding="utf-8")
PY
git -C "$SITE_DIR" add kustomization.yaml node-config
if ! git -C "$SITE_DIR" diff --cached --quiet; then
  git -C "$SITE_DIR" -c user.name=fn-dev -c user.email=fn-dev@example.org \
    commit -q -m "Site: bootstrap demo Nexus resources"
fi
gitea_git -C "$SITE_DIR" push -q --force-with-lease -u origin "$RESOURCES_BRANCH"
git -C "$SITE_DIR" checkout -q main

resources_pr="$(open_or_update_pr "$RESOURCES_BRANCH" \
  "Site: bootstrap demo Nexus resources" \
  "Declare the Gitea provider, repositories, credentials and demo project.")"
echo "Resources PR: $(pr_url "$resources_pr")"
wait_for_merge "$resources_pr" "The operator will reconcile the project after this PR merges."
flux reconcile kustomization "$SITE_REPO" -n flux-system --with-source
"$FNCLI" gitea setup -f flux/examples/site/node-config/gitea.yaml \
  -f flux/examples/site/node-config/demo.yaml
wait_for_fn_resources "gitea-local demo-trigger-repo-creds demo-results-repo-creds demo-trigger-repo demo-results-repo demo-gitea"

echo "== Running the demo trigger and results flow"
export FN_USERNAME="${FN_USERNAME:-dagster}"
if [ -z "${FN_PASSWORD:-}" ] && [ "$FN_USERNAME" = dagster ]; then
  FN_PASSWORD="$(kubectl get secret dagster-keycloak-creds -n keycloak \
    -o jsonpath='{.data.DAGSTER_KC_PASSWORD}' | base64 -d)"
  export FN_PASSWORD
fi
"$FNCLI" start-sensor --group all
"$FNCLI" trigger triggers/examples/demo.json \
  --project demo-gitea --pr --merge --watch --timeout 600

echo
echo "Flux demo completed. Site: $GITEA_URL/$GITEA_ADMIN_USER/$SITE_REPO"
