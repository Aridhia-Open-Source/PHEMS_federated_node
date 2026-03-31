#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Kind Cluster Create / Delete
###############################################################################

CLUSTER_NAME="fn"
KIND_CONFIG_FILE=".kind/kind-config.yaml"

COMMAND="${1:-}"

usage() {
  echo "Usage: $0 <create|delete>"
  exit 1
}

case "$COMMAND" in
  create)
    echo "=== Creating kind cluster '$CLUSTER_NAME' ==========================="

    kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG_FILE"

    docker network connect kind kind-registry              || true
    docker network connect kind proxy-docker-hub-registry  || true
    docker network connect kind proxy-ghcr-registry        || true

    kubectl config use-context "kind-$CLUSTER_NAME"
    kubectl apply -f .kind/docker-registry.yaml

    echo "=== Cluster '$CLUSTER_NAME' ready ==================================="
    ;;

  delete)
    echo "=== Deleting kind cluster '$CLUSTER_NAME' ==========================="
    kind delete cluster --name "$CLUSTER_NAME"
    echo "=== Done ============================================================"
    ;;

  *)
    usage
    ;;
esac