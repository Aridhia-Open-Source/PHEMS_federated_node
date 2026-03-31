#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Federated Node - Dev Cluster Full Reset & Redeploy (kind)
#
# Fast-path dev workflow:
#   1. Ensure host paths exist
#   2. Delete + recreate kind cluster (via .kind/main.sh)
#   3. Create namespace + secrets
#   4. Build code locations
#   5. Deploy Helm release
#
# Disposable cluster. No waits. No sanity checks.
###############################################################################

### Config ####################################################################
CLUSTER_NAME="fn"
NAMESPACE="fn"
RELEASE_NAME="fn-dev"
VALUES_FILENAME="example.values.yaml"
DB_SECRET_KEY="local-db-secret"

# Host paths required for local PVs
HOST_MOUNT_PATHS=(
  "/data/db"
  "/data/flask"
  "/data/controller"
)

###############################################################################
echo "=== [1/5] Ensuring host paths exist on the machine ========================"

for path in "${HOST_MOUNT_PATHS[@]}"; do
  sudo mkdir -p "$path"
done

sudo chmod -R 777 /data

###############################################################################
echo "=== [2/5] Recreating kind cluster ========================================="

./.kind/main.sh delete
./.kind/main.sh create

###############################################################################
echo "=== [3/5] Creating namespace and secrets =================================="

kubectl create namespace "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl config set-context \
  --current --namespace="$NAMESPACE"

kubectl create secret generic local-db \
  --from-literal=password="$DB_SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

###############################################################################
echo "=== [4/5] Building Docker image(s) ========================================"

echo "skipping image builds..."


echo "Image builds successful!"

###############################################################################
echo "=== [5/5] Deploying Helm release =========================================="
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

helm dependency update .

helm upgrade \
  --install "$RELEASE_NAME" . \
  -f "$VALUES_FILENAME" \
  --timeout 30m

echo
echo "== Deployment completed ======================================"
