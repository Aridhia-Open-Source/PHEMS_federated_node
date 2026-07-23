#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Federated Node - Cluster Management
#
# Usage:
#   ./scripts/cluster.sh up                        # Start cluster + registries
#   ./scripts/cluster.sh down                      # Delete cluster, keep registries
#   ./scripts/cluster.sh down --remove-registries  # Delete everything
####################################################################################

COMMAND="${1:-}"
REMOVE_REGISTRIES="${2:-false}"

# Load env
source .dev.env

CLUSTER_NAME="${CLUSTER_NAME:-fn}"
KIND_CONFIG_FILE=".kind/kind-config.yaml"

# Show usage if no command
if [ -z "$COMMAND" ] || [ "$COMMAND" != "up" ] && [ "$COMMAND" != "down" ]; then
  echo "Usage: $0 <up|down> [--remove-registries]"
  echo ""
  echo "Commands:"
  echo "  up                              Start Kind cluster + Docker registries"
  echo "  down                            Delete cluster, keep registries"
  echo "  down --remove-registries        Delete cluster and all registries"
  exit 1
fi


###############################################################################
# UP - Start cluster and registries
###############################################################################
if [ "$COMMAND" = "up" ]; then
  echo "=== Starting Docker Registries =========================================="

  # Start kind-registry
  if [ "$(docker inspect -f '{{.State.Running}}' "kind-registry" 2>/dev/null || true)" != "true" ]; then
    echo "Starting kind-registry on localhost:5001..."
    docker run \
      -d --restart=always \
      -p "127.0.0.1:5001:5000" \
      --name kind-registry \
      registry:2
  else
    echo "kind-registry already running"
  fi

  # Start proxy-docker-hub-registry
  if [ "$(docker inspect -f '{{.State.Running}}' "proxy-docker-hub-registry" 2>/dev/null || true)" != "true" ]; then
    echo "Starting proxy-docker-hub-registry on localhost:5002..."
    docker run \
      -d --restart=always \
      -p "127.0.0.1:5002:5000" \
      -e REGISTRY_PROXY_REMOTEURL=https://registry-1.docker.io \
      --name proxy-docker-hub-registry \
      registry:2
  else
    echo "proxy-docker-hub-registry already running"
  fi

  # Start proxy-ghcr-registry
  if [ "$(docker inspect -f '{{.State.Running}}' "proxy-ghcr-registry" 2>/dev/null || true)" != "true" ]; then
    echo "Starting proxy-ghcr-registry on localhost:5003..."
    docker run \
      -d --restart=always \
      -p "127.0.0.1:5003:5000" \
      -e REGISTRY_PROXY_REMOTEURL=https://ghcr.io \
      --name proxy-ghcr-registry \
      registry:2
  else
    echo "proxy-ghcr-registry already running"
  fi

  echo
  echo "=== Creating Kind Cluster ==============================================="

  # Check if cluster already exists
  if kind get clusters | grep -q "^$CLUSTER_NAME$"; then
    echo "Kind cluster '$CLUSTER_NAME' already exists"
  else
    echo "Creating Kind cluster '$CLUSTER_NAME'..."
    kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG_FILE"
  fi

  # Ensure registries are connected to kind network
  echo "Connecting registries to kind network..."
  docker network connect kind kind-registry 2>/dev/null || true
  docker network connect kind proxy-docker-hub-registry 2>/dev/null || true
  docker network connect kind proxy-ghcr-registry 2>/dev/null || true

  # Apply registry discovery metadata
  echo "Applying registry discovery ConfigMap..."
  kubectl config use-context "kind-$CLUSTER_NAME"
  kubectl apply -f .kind/docker-registry.yaml

  echo
  echo "=== Cluster Ready ======================================================"
  echo "Cluster: $CLUSTER_NAME"
  echo "Context: kind-$CLUSTER_NAME"
  echo
  echo "Registries:"
  echo "  localhost:5001 - local registry"
  echo "  localhost:5002 - Docker Hub mirror"
  echo "  localhost:5003 - GHCR mirror"
  echo
  echo "Next steps:"
  echo "  1. Create namespace: kubectl create namespace $NAMESPACE"
  echo "  2. Deploy Helm: ./scripts/deploy.sh"
  echo "  3. Or use Tilt: tilt up"
  echo


###############################################################################
# DOWN - Tear down cluster
###############################################################################
elif [ "$COMMAND" = "down" ]; then
  echo "=== Stopping Tilt (if running) =========================================="
  tilt down 2>/dev/null || true

  echo
  echo "=== Deleting Kind Cluster ==============================================="
  kind delete cluster --name "$CLUSTER_NAME" || true

  echo
  if [ "$REMOVE_REGISTRIES" = "--remove-registries" ]; then
    echo "=== Removing Docker Registries =========================================="

    docker stop kind-registry 2>/dev/null || echo "kind-registry not running"
    docker rm kind-registry 2>/dev/null || echo "kind-registry not found"
    echo "Removed kind-registry"

    docker stop proxy-docker-hub-registry 2>/dev/null || echo "proxy-docker-hub-registry not running"
    docker rm proxy-docker-hub-registry 2>/dev/null || echo "proxy-docker-hub-registry not found"
    echo "Removed proxy-docker-hub-registry"

    docker stop proxy-ghcr-registry 2>/dev/null || echo "proxy-ghcr-registry not running"
    docker rm proxy-ghcr-registry 2>/dev/null || echo "proxy-ghcr-registry not found"
    echo "Removed proxy-ghcr-registry"

    echo
    echo "Registries removed. Images will need to be rebuilt from scratch."
  else
    echo "=== Keeping Docker Registries =========================================="
    echo "Registries are still running:"
    docker ps 2>/dev/null | grep -E "kind-registry|proxy.*registry" || echo "No registries found"
    echo
    echo "To remove registries, run:"
    echo "  ./scripts/cluster.sh down --remove-registries"
  fi

  echo
  echo "=== Cleanup Complete ===================================================="
  echo "Kind cluster '$CLUSTER_NAME' deleted"
  echo
  echo "To restart:"
  echo "  make cluster up                            # Just cluster + registries"
  echo "  make deploy                                # Full deployment with Helm"
  echo "  tilt up                                    # Start Tilt dev environment"
  echo
fi
