#!/usr/bin/env bash
set -euo pipefail

# Load env
source .dev.env

echo "=== Building Dagster image ==="
./scripts/build_image.sh dagster "$DOCKER_TAG"

echo "=== Building Webserver image ==="
./scripts/build_image.sh webserver "$DOCKER_TAG"

echo
echo "=== Restarting Dagster pods ==="
kubectl rollout restart deployment/${RELEASE_NAME}-dagster-daemon -n "$NAMESPACE"
kubectl rollout restart deployment/${RELEASE_NAME}-dagster-webserver -n "$NAMESPACE"
kubectl rollout restart deployment/${RELEASE_NAME}-dagster-user-deployments-dagster-${CLUSTER_NAME} -n "$NAMESPACE"

echo "=== Restarting Backend pod ==="
kubectl rollout restart deployment/backend -n "$NAMESPACE"

echo
echo "=== Waiting for rollout to complete ==="
kubectl rollout status deployment/backend -n "$NAMESPACE" --timeout=5m

echo
echo "=== Pods refreshed successfully ==="
kubectl get pods -n "$NAMESPACE" | grep -E "dagster|backend"
