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
  cp .demo.env.example .demo.env
  # DOCKER_TAG has to match the image tag in the values file (see First time in DEPLOYMENT.md).
  tag="$(grep -m1 -oE '(tag:|&devTag) *"?v[0-9]+' k8s/federated-node/dev.values.yaml | grep -oE 'v[0-9]+' || true)"
  [ -z "$tag" ] || sed -i "s/^DOCKER_TAG=.*/DOCKER_TAG=$tag/" .dev.env
  # A CA for the cluster and release to trust, see .dev.env.example.
  [ -z "${CUSTOM_CA_FILE:-}" ] || echo "CUSTOM_CA_FILE=$CUSTOM_CA_FILE" >> .dev.env
}

step_helm_deps() { set -e; make helm_deps; }

step_cluster_up() { set -e; make cluster up; }

step_deploy() { set -e; make deploy; }

# Tilt has to outlive this script: the demo needs its port-forwards.
step_tilt_up() {
  set -e
  pkill -x tilt || true   # a Tilt left over from before a redeploy keeps stale port-forwards
  sleep 2
  setsid nohup tilt up --stream > /work/tilt.log 2>&1 < /dev/null &
  # The demo needs the port-forwards: backend, Dagster, Gitea and Keycloak.
  for port in 5000 3000 4000 8080; do
    echo "waiting for localhost:$port"
    timeout 1200 bash -c "until curl -s -o /dev/null -m 5 http://localhost:$port/; do sleep 5; done"
  done
}

step_install_fncli() {
  set -e
  pipx install --force --editable './dagster[cli]'
  fncli hello-world
}

# Tilt replaces the code server right after it starts, and the Dagster webserver then keeps
# showing "could not reach user code server" until the location is reloaded (the UI's Reload).
step_start_sensors() {
  curl -s -m 60 localhost:3000/graphql -H 'content-type: application/json' \
    -d '{"query":"mutation { reloadRepositoryLocation(repositoryLocationName: \"dagster-fn\") { __typename } }"}' >/dev/null || true
  for i in $(seq 1 18); do
    fncli start-sensor --group all && return 0
    echo "sensors not loaded yet (try $i), waiting"
    sleep 10
  done
  return 1
}

step_demo() { set -e; fncli demo -y; }

step configure
step helm_deps
step cluster_up
step deploy
step tilt_up
step install_fncli
step start_sensors
step demo

echo
echo "=== All steps passed ==="
