#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Helm Deployment - Sets up namespaces, secrets, and deploys Helm release
###############################################################################

source .dev.env

# Use DB_SECRET_KEY for both services
BACKEND_DB_SECRET_KEY=$DB_SECRET_KEY
DAGSTER_DB_SECRET_KEY=$DB_SECRET_KEY

# Host paths required for local PVs
HOST_MOUNT_PATHS=(
  "/data/db"
  "/data/flask"
  "/data/controller"
  "/data/dagster/artifacts"
)


echo "=== Creating Namespace =================================================="
kubectl create namespace "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl config set-context \
  --current --namespace="$NAMESPACE"


echo "=== Creating Secrets ==================================================="
kubectl create secret generic local-db \
  --from-literal=password="$BACKEND_DB_SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic dagster-postgresql-secret \
  --from-literal=postgresql-password="$DAGSTER_DB_SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic github-token \
  --from-literal=GH_TOKEN="$GH_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic keycloak-first-user \
  --from-literal=PASSWORD="$KEYCLOAK_FIRST_USER_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f - -n "$NAMESPACE"


echo "=== Reconciling PersistentVolumes ======================================"

echo "resetting persistent host volumes..."

for path in "${HOST_MOUNT_PATHS[@]}"; do
  echo "reset volume $path"
  sudo rm -rf $path
  sudo mkdir -p "$path"
done

sudo chmod -R 777 /data

# All PVs (db, backend-results, dagster-artifacts) are plain, Helm-managed
# resources with reclaimPolicy: Retain and are reconciled idempotently by
# `helm upgrade` -- we must NOT delete PVs/PVCs here (they may be mounted by a
# running pod, and deleting a mounted PVC/PV deadlocks on its finalizer).
#
# The only recurring hazard is a Retain PV left in "Released" state by an
# earlier run (its PVC was deleted): it holds a stale claimRef and refuses to
# rebind to the PVC Helm recreates, leaving the pod stuck Pending. Clearing the
# claimRef returns it to Available so it rebinds. This is non-blocking and safe.
for pv in $(kubectl get pv -o jsonpath='{range .items[?(@.status.phase=="Released")]}{.metadata.name}{"\n"}{end}' 2>/dev/null); do
  case "$pv" in
    "$RELEASE_NAME"-*) kubectl patch pv "$pv" -p '{"spec":{"claimRef":null}}';;
  esac
done

echo "=== Deploying Helm Release =============================================="

cd k8s/federated-node

helm upgrade \
  --install "$RELEASE_NAME" . \
  -f "$VALUES_FILE" \
  --timeout 10m \
  --namespace "$NAMESPACE"

cd - > /dev/null

echo
echo "=== Helm Deployment Complete ==========================================="
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE_NAME"
echo
echo "Watch pods with:"
echo "  kubectl get pods -n $NAMESPACE -w"
echo
