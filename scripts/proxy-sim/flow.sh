#!/usr/bin/env bash
###################################################################################
# A colleague's first run, inside the fake laptop (see scripts/proxy-sim.sh).
# The steps follow DEPLOYMENT.md "Run it locally". Stops at the first one that fails.
#
#   flow.sh [--from N]      # resume at step N after a failure
#
# Each step's output is also kept in /work/logs.
####################################################################################
set -uo pipefail

# A login shell sets this; docker exec does not, and deploy_owner.sh needs it.
export USER="${USER:-$(id -un)}"

FROM=1
[ "${1:-}" = "--from" ] && FROM="${2:?--from needs a step number}"

LOG_DIR=/work/logs
mkdir -p "$LOG_DIR"
N=0

step() {
  local name="$1"
  N=$((N + 1))
  [ "$N" -lt "$FROM" ] && return 0
  echo
  echo "=== step $N: $name ==========================================="
  local log="$LOG_DIR/$N-${name// /_}.log"
  "step_${name// /_}" 2>&1 | tee "$log"
  local rc="${PIPESTATUS[0]}"
  if [ "$rc" -ne 0 ]; then
    echo
    echo "FAILED at step $N ($name), exit $rc. Log: $log"
    echo "Fix it, then resume with: --from $N"
    exit "$rc"
  fi
}

step_configure() {
  set -e
  cp .dev.env.example .dev.env
  sed -i 's/^KEYCLOAK_FIRST_USER_EMAIL=.*/KEYCLOAK_FIRST_USER_EMAIL=admin@example.com/' .dev.env
  sed -i 's/^KEYCLOAK_FIRST_USER_PASSWORD=.*/KEYCLOAK_FIRST_USER_PASSWORD=Admin-Pass-123/' .dev.env
  # proxy-sim.sh sync copies the host's dev.values.yaml in when there is one: the example has no Gitea.
  [ -f k8s/federated-node/dev.values.yaml ] || cp k8s/federated-node/dev.example.values.yml k8s/federated-node/dev.values.yaml
  # A CA for the cluster and release to trust, see .dev.env.example.
  [ -z "${CUSTOM_CA_FILE:-}" ] || echo "CUSTOM_CA_FILE=$CUSTOM_CA_FILE" >> .dev.env
}

# kind, kubectl, helm and tilt come from mise, which the laptop image carries; this downloads them.
step_setup() { set -e; mise trust --all && mise run setup; }

step_helm_deps() { set -e; mise run helm-deps; }

step_cluster_up() { set -e; mise run cluster-up; }

step_deploy() { set -e; mise run deploy; }

# Tilt has to outlive this script: its port-forwards are how you reach the node.
step_tilt_up() {
  set -e
  pkill -x tilt || true   # a Tilt left over from before a redeploy keeps stale port-forwards
  sleep 2
  setsid nohup tilt up --stream > /work/tilt.log 2>&1 < /dev/null &
  # The port-forwards: backend, Dagster, Gitea and Keycloak.
  for port in 5000 3000 4000 8080; do
    echo "waiting for localhost:$port"
    timeout 1200 bash -c "until curl -s -o /dev/null -m 5 http://localhost:$port/; do sleep 5; done"
  done
}

step configure
step setup
step helm_deps
step cluster_up
step deploy
step tilt_up

echo
echo "=== All steps passed ==="
