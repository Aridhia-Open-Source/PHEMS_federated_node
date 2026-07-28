#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Helm Deployment - Sets up namespaces, secrets, and deploys Helm release
###############################################################################

source .dev.env

# Host paths required for local PVs
HOST_MOUNT_ROOT_PATH="/data"

HOST_MOUNT_PATHS=(
  "/data/db"
  "/data/flask"
  "/data/controller"
  "/data/dagster/artifacts"
)

echo
echo "=== Terminating tilt sessions =================================================="

if command -v tilt &> /dev/null; then
  if pgrep -f "tilt serve" > /dev/null; then
    tilt down
    echo "Terminated tilt session"
  else
    echo "No tilt sessions found"
  fi
fi

echo
echo "=== Reconciling PersistentVolumes ======================================"

echo "sudo mkdir $HOST_MOUNT_ROOT_PATH"
sudo mkdir -p $HOST_MOUNT_ROOT_PATH

for path in "${HOST_MOUNT_PATHS[@]}"; do
  echo "sudo mkdir $path"
  sudo mkdir -p "$path"
done

echo "sudo chmod -R 777 $HOST_MOUNT_ROOT_PATH"
sudo chmod -R 777 /data

echo
echo "=== Building Docker Images(s) ========================================"

./scripts/build_all_images.sh $DOCKER_TAG

echo
echo "=== Creating Namespaces =================================================="
kubectl create namespace "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create namespace keycloak \
  --dry-run=client -o yaml | kubectl apply -f -

echo
echo "=== Creating Secrets ==================================================="
kubectl create secret generic postgres-superuser \
  --from-literal=password="$POSTGRES_PASSWORD" \
  --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic backend-db \
  --from-literal=password="$BACKEND_DB_PASSWORD" \
  --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic dagster-postgresql-secret \
  --from-literal=postgresql-password="$DAGSTER_PG_PASSWORD" \
  --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic keycloak-db-secret \
  --from-literal=password="$KC_DB_PASSWORD" \
  --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic keycloak-first-user \
  --from-literal=PASSWORD="$KEYCLOAK_FIRST_USER_PASSWORD" \
  --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic github-token \
  --from-literal=GH_TOKEN="$GH_TOKEN" \
  --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"

echo
echo "=== Deploying Helm Release =============================================="

cd k8s/federated-node

helm upgrade \
  --install "$RELEASE_NAME" . \
  -f "$VALUES_FILE" \
  --timeout 10m \
  --namespace "$NAMESPACE"

cd - > /dev/null

kubectl config set-context \
  --current --namespace="$NAMESPACE"

echo
echo "=== Helm Deployment Complete ==========================================="
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE_NAME"
echo
echo "Watch pods with:"
echo "  kubectl get pods -n $NAMESPACE -w"
echo
