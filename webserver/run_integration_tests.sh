#!/bin/bash
# Integration tests: kc-init against a real Keycloak, over MULTIPLE runs on the same database.
#
# Running kc-init once against a fresh database cannot catch the bug that motivated this work: setup
# succeeded the first time and silently did nothing every time after, because its only credential was
# the bootstrap user it deleted on the way out. Step 01 is the single-run case; everything after it
# needs the same Keycloak without a restart.
#
# Each assertion fails against the pre-fix code. That is the bar -- a test that passes both before
# and after proves nothing.
#
# This script owns the stack: it brings Keycloak up once, then runs each numbered step in
# integration_tests/ in order and sums their exit codes. Steps are ordered because they share one
# Keycloak and assert across each other's kc-init runs; they are not independent.
set -uo pipefail

cd "$(dirname "$0")"

STEPS_DIR="integration_tests"
export COMPOSE_FILE="docker-compose-integration-tests.yaml"
COMPOSE="docker compose -f $COMPOSE_FILE"

export PGHOST=db PGDATABASE=test_app PGPORT=5432 PGUSER=admin PGPASSWORD=test_app
export KEYCLOAK_URL=http://keycloak:8080 KEYCLOAK_REALM=FederatedNode KEYCLOAK_CLIENT=global
export KC_BOOTSTRAP_ADMIN_USERNAME=tmpadmin-1 KC_BOOTSTRAP_ADMIN_PASSWORD=password1
export KEYCLOAK_ADMIN=admin KEYCLOAK_ADMIN_PASSWORD=password1
export KEYCLOAK_SERVICE_USER=fn-service KEYCLOAK_SERVICE_PASSWORD=servicepass1
export KEYCLOAK_SECRET=qwtirtvJJ4PW4skOlW6Oifk2
export KEYCLOAK_TOKEN_LIFE=3600 KEYCLOAK_LOGLEVEL=INFO
export PYTHONPATH=/app RESULTS_PATH=/tmp/results TASK_POD_RESULTS_PATH=/mnt/data
export DEFAULT_NAMESPACE=default TASK_NAMESPACE=tasks KEYCLOAK_NAMESPACE=keycloak
export CLEANUP_AFTER_DAYS=1 PUBLIC_URL=localhost:5000 CLAIM_CAPACITY=100Mi
export CONTROLLER_NAMESPACE=fn-controller

# Where steps leave each kc-init run's output for the steps that assert across runs.
ARTIFACTS="$(mktemp -d)"
export ARTIFACTS

failures=0

cleanup() {
  echo "Cleaning up"
  $COMPOSE down -v >/dev/null 2>&1
  rm -rf "$ARTIFACTS"
}
trap cleanup EXIT

echo "=== Bringing up Keycloak ==="
$COMPOSE down -v >/dev/null 2>&1
$COMPOSE up -d --build db keycloak >/dev/null 2>&1 || { echo "failed to start stack"; exit 1; }

for _ in $(seq 1 60); do
  $COMPOSE ps keycloak 2>/dev/null | grep -q healthy && break
  sleep 3
done
if ! $COMPOSE ps keycloak 2>/dev/null | grep -q healthy; then
  echo "Keycloak never became healthy"; $COMPOSE logs keycloak | tail -30; exit 1
fi

KC_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' keycloak_test)
export KC_IP
echo "Keycloak healthy at $KC_IP"

# Numbered steps only: files prefixed with `_` are helpers for a step, not steps themselves.
steps=("$STEPS_DIR"/[0-9][0-9]_*)
if [[ ! -e "${steps[0]}" ]]; then
  echo "No test steps found in $STEPS_DIR"; exit 1
fi

for step in "${steps[@]}"; do
  echo ""
  case "$step" in
    *.py) PYTHONPATH="$STEPS_DIR" python3 "$step" ;;
    *.sh) bash "$step" ;;
    *) echo "Don't know how to run $step"; exit 1 ;;
  esac
  # Every step exits with its own failure count, so this sums to a total across the suite.
  failures=$((failures + $?))
done

echo ""
if [[ $failures -eq 0 ]]; then
  echo "All integration tests passed."
else
  echo "$failures check(s) FAILED."
  # Each kc-init run's output is echoed inline by the step that ran it; this is the server side of a
  # failure, which is otherwise thrown away when the stack comes down.
  echo ""
  echo "=== Keycloak server log (last 50 lines) ==="
  $COMPOSE logs keycloak 2>&1 | tail -50
fi
exit $failures
