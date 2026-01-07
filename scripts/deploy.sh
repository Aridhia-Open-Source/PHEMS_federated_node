#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Federated Node - Dev Cluster Full Reset & Redeploy (kind)
#
# Fast-path dev workflow:
#   1. Delete existing kind cluster
#   2. Recreate cluster with required mounts
#   3. Apply local registry discovery metadata
#   4. Create namespace + secrets
#   5. Deploy Helm release
#   6. Ensure local Docker registry is running
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

REGISTRY_NAME='kind-registry'
REGISTRY_PORT='5001'

# Host paths required by hostPath / local PVs
HOST_MOUNT_PATHS=(
  "/data/flask"
  "/data/db"
  "/data/controller"
)

###############################################################################
echo "=== [1/7] Ensuring host paths exist on the machine ========================"

for path in "${HOST_MOUNT_PATHS[@]}"; do
  sudo mkdir -p "$path"
done

# Dev-friendly permissions
sudo chmod -R 777 /data

###############################################################################
echo "=== [2/7] Deleting existing kind cluster (if it exists) ==================="

kind delete cluster --name "$CLUSTER_NAME" || true
docker rm -f "${CLUSTER_NAME}-control-plane" || true

###############################################################################
echo "=== [3/7] Creating kind cluster ==========================================="

kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG_FILE"

###############################################################################
echo "=== [4/7] Applying local registry discovery metadata ======================="

kubectl apply -f .kind/docker-registry.yaml

echo "=== [5/7] Ensuring local Docker registry is running ========================"

if [ "$(docker inspect -f '{{.State.Running}}' "${REGISTRY_NAME}" 2>/dev/null || true)" != 'true' ]; then
  docker run \
    -d --restart=always \
    -p "127.0.0.1:${REGISTRY_PORT}:5000" \
    --network bridge \
    --name "${REGISTRY_NAME}" \
    registry:2
fi

docker network connect kind kind-registry || true


###############################################################################
echo "=== [6/7] Creating namespace and secrets =================================="

kubectl create namespace "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic local-db \
  -n "$NAMESPACE" \
  --from-literal=password="$DB_SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

###############################################################################
echo "=== [7/7] Deploying Helm release =========================================="

cd k8s/federated-node

helm upgrade \
  --install "$RELEASE_NAME" . \
  -n "$NAMESPACE" \
  -f "$VALUES_FILE"


###############################################################################
echo "=== Deployment triggered =================================================="
echo
echo "Watch progress with:"
echo "  kubectl get pods -n $NAMESPACE -w"
echo
echo "Set context with:"
echo "  kubectl config set-context --current --namespace=$NAMESPACE"
echo
echo "If something fails:"
echo "  - Fix config"
echo "  - Rerun this script"
###############################################################################
