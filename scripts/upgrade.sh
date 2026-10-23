#!/usr/bin/env bash

set -euo pipefail

###############################################################################
# Helm upgrade only - no image builds, no secret or host-path setup.
# Use scripts/deploy.sh for a full deploy.
###############################################################################

source .dev.env

./scripts/deploy_owner.sh claim

# Tilt injects a `command` the chart does not manage, so Helm's three-way merge keeps
# it while resetting the image, and the pod then dies on a missing
# /tilt-restart-wrapper. deploy.sh stops Tilt first for the same reason.
if command -v tilt &> /dev/null && pgrep -f "tilt up" > /dev/null; then
  echo "=== Terminating tilt session ==="
  tilt down
fi

# CUSTOM_CA_FILE (optional): a CA the release trusts for outbound TLS. See custom_ca.sh.
source ./scripts/custom_ca.sh
custom_ca_prepare

cd k8s/federated-node

kubectl config set-context \
  --current --namespace="$NAMESPACE"

helm upgrade \
  --install "$RELEASE_NAME" . \
  -f "$VALUES_FILE" \
  --set "firstUserSecret.email=$KEYCLOAK_FIRST_USER_EMAIL" \
  ${CUSTOM_CA_HELM_ARGS[@]+"${CUSTOM_CA_HELM_ARGS[@]}"} \
  --timeout 30m \
  --namespace "$NAMESPACE"

# Only the app deployments, not Keycloak and the Postgres instances too.
kubectl rollout restart -n "$NAMESPACE" \
  deployment/backend \
  "deployment/${RELEASE_NAME}-${DAGSTER_USER_DEPLOYMENT:-dagster-fn}" \
  "deployment/${RELEASE_NAME}-dagster-daemon" \
  "deployment/${RELEASE_NAME}-dagster-webserver"
