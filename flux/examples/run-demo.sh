#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

source scripts/load_env.sh

if [ -x "$ROOT/.venv/bin/fncli" ]; then
  FNCLI="$ROOT/.venv/bin/fncli"
else
  FNCLI="$(command -v fncli || true)"
fi
[ -n "$FNCLI" ] || { echo "fncli is not installed; run mise run setup first" >&2; exit 1; }

PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

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

echo "== Checking the Flux-managed application and demo project"
kubectl wait helmrelease/federated-node -n "${NAMESPACE:-fn}" --for=condition=Ready --timeout=30m
kubectl get project demo-gitea -n fn-operator -o wide

echo "== Starting local API, Dagster and Keycloak port-forwards"
start_forward fn nexus-api 5000 5000 http://localhost:5000/health_check
start_forward fn fn-dev-dagster-webserver 3000 80 http://localhost:3000
start_forward keycloak keycloak 8080 80 http://localhost:8080

export GITEA_LOCAL_URL="${GITEA_LOCAL_URL:-http://localhost:4000}"
export FN_USERNAME="${FN_USERNAME:-dagster}"
if [ -z "${FN_PASSWORD:-}" ] && [ "$FN_USERNAME" = dagster ]; then
  FN_PASSWORD="$(kubectl get secret dagster-keycloak-creds -n keycloak \
    -o jsonpath='{.data.DAGSTER_KC_PASSWORD}' | base64 -d)"
  export FN_PASSWORD
fi

echo "== Starting Dagster sensors"
"$FNCLI" start-sensor --group all

echo "== Creating and watching the demo trigger PR"
"$FNCLI" trigger triggers/examples/demo.json \
  --project demo-gitea --pr --merge --watch --timeout 600

echo
echo "Demo trigger and results flow completed."
