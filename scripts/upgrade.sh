#!/usr/bin/env bash

set -euo pipefail

###############################################################################
# Helm upgrade only - no image builds, no secret or host-path setup.
# Use scripts/deploy.sh for a full deploy.
###############################################################################

source .dev.env

# Tilt injects a `command` the chart does not manage, so Helm's three-way merge keeps
# it while resetting the image, and the pod then dies on a missing
# /tilt-restart-wrapper. deploy.sh stops Tilt first for the same reason.
if command -v tilt &> /dev/null && pgrep -f "tilt up" > /dev/null; then
  echo "=== Terminating tilt session ==="
  tilt down
fi

cd k8s/federated-node

kubectl config set-context \
  --current --namespace="$NAMESPACE"

helm upgrade \
  --install "$RELEASE_NAME" . \
  -f "$VALUES_FILE" \
  --timeout 30m \
  --namespace "$NAMESPACE"

# Only the app deployments, not Keycloak and the Postgres instances too.
kubectl rollout restart -n "$NAMESPACE" \
  deployment/backend \
  "deployment/${RELEASE_NAME}-${DAGSTER_USER_DEPLOYMENT:-dagster-fn}" \
  "deployment/${RELEASE_NAME}-dagster-daemon" \
  "deployment/${RELEASE_NAME}-dagster-webserver"
