#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Federated Node - Dev Cluster Full Reset & Redeploy (kind)
#
# Fast-path dev workflow:
#   1. Ensure local Docker registry is running
#   2. Delete existing kind cluster
#   3. Recreate cluster with required mounts
#   4. Apply local registry discovery metadata
#   5. Create namespace + secrets
#   6. Build code locations
#   7. Deploy Helm release
#
# Disposable cluster. No waits. No sanity checks.
###############################################################################

### CONFIG ####################################################################

CLUSTER_NAME="fn"
NAMESPACE="fn"
RELEASE_NAME="fn-dev"
VALUES_FILE=".values/dev.values.yaml"
KIND_CONFIG_FILE=".kind/kind-config.yaml"
DB_SECRET_KEY="local-db-secret"
REGISTRY_NAME="kind-registry"
REGISTRY_PORT="5001"

# Host paths required by hostPath / local PVs
HOST_MOUNT_PATHS=(
  "/data/flask"
  "/data/db"
  "/data/controller"
)

###############################################################################
echo "=== [1/8] Ensuring host paths exist on the machine ========================"

for path in "${HOST_MOUNT_PATHS[@]}"; do
  sudo mkdir -p "$path"
done

# Dev-friendly permissions
sudo chmod -R 777 /data

###############################################################################
echo "=== [2/8] Ensuring local Docker registry is running ========================"

if [ "$(docker inspect -f '{{.State.Running}}' "${REGISTRY_NAME}" 2>/dev/null || true)" != "true" ]; then
  docker run \
    -d --restart=always \
    -p "127.0.0.1:${REGISTRY_PORT}:5000" \
    --name "${REGISTRY_NAME}" \
    registry:2
fi

###############################################################################
echo "=== [3/8] Deleting existing kind cluster (if it exists) ==================="

kind delete cluster --name "$CLUSTER_NAME" || true

###############################################################################
echo "=== [4/8] Creating kind cluster ==========================================="

kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG_FILE"

# Ensure registry is reachable from the kind network
docker network connect kind "$REGISTRY_NAME" || true

###############################################################################
echo "=== [5/8] Applying local registry discovery metadata ======================="

kubectl config use-context "kind-$CLUSTER_NAME"
kubectl apply -f .kind/docker-registry.yaml

###############################################################################
echo "=== [6/8] Creating namespace and secrets =================================="

kubectl create namespace "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic local-db \
  -n "$NAMESPACE" \
  --from-literal=password="$DB_SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

###############################################################################
echo "=== [7/8] Building Code Location(s) ========================================"

cd dagster
# ./compile.sh  # enable if dependencies changed
./build.sh
cd ..

###############################################################################
echo "=== [8/8] Deploying Helm release =========================================="
echo
echo "Watch pods with:"
echo "  kubectl get pods -n $NAMESPACE -w"
echo
echo "Watch events with:"
echo "  kubectl get events -n $NAMESPACE --sort-by='.metadata.creationTimestamp' -w"
echo
echo "If something fails:"
echo "  - Fix config"
echo "  - Rerun this script"
echo

cd k8s/federated-node

kubectl config set-context --current --namespace="$NAMESPACE"

helm upgrade \
  --install "$RELEASE_NAME" . \
  -f "$VALUES_FILE" \
  --timeout 20m \
  --wait

echo
echo "=== Deployment completed ======================================"
