#!/usr/bin/env bash
set -euo pipefail

# Load env
source .dev.env

echo "=== Building Dagster and nexus-api images ==="
scripts/build_images.sh dagster-fn nexus-api-fn

echo
echo "=== Restarting Dagster pods ==="
# The code server is part of this chart: <release>-<fnDagster.codeServer.name>.
DAGSTER_USER_DEPLOYMENT="${DAGSTER_USER_DEPLOYMENT:-dagster-fn}"
kubectl rollout restart deployment/${RELEASE_NAME}-dagster-daemon -n "$NAMESPACE"
kubectl rollout restart deployment/${RELEASE_NAME}-dagster-webserver -n "$NAMESPACE"
kubectl rollout restart "deployment/${RELEASE_NAME}-${DAGSTER_USER_DEPLOYMENT}" -n "$NAMESPACE"

echo "=== Restarting nexus-api pod ==="
kubectl rollout restart deployment/nexus-api -n "$NAMESPACE"

echo
echo "=== Waiting for rollout to complete ==="
kubectl rollout status deployment/nexus-api -n "$NAMESPACE" --timeout=5m

echo
echo "=== Pods refreshed successfully ==="
kubectl get pods -n "$NAMESPACE" | grep -E "dagster|nexus-api"
