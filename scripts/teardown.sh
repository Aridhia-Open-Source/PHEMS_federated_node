#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Teardown - Completely removes deployment and persistent data
###############################################################################

source .dev.env

# Host paths required for local PVs
HOST_MOUNT_ROOT_PATH="/data"

HOST_MOUNT_PATHS=(
  "/data/db"
  "/data/flask"
  "/data/controller"
  "/data/dagster/artifacts"
  "/data/datasets"
)


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
echo "=== Uninstalling deployment =================================================="
if helm uninstall $RELEASE_NAME -n $NAMESPACE 2>/dev/null; then
  echo "Uninstalled existing release: $RELEASE_NAME"
else
  echo "Release '$RELEASE_NAME' not found, skipping uninstall"
fi

echo
echo "=== Clearing root mount path ================================================"
# Delete the *contents*, not the directory. .kind/kind-config.yaml bind-mounts
# $HOST_MOUNT_ROOT_PATH into the kind node, and that mount is bound to the inode
# as it was at cluster creation. Removing the directory leaves the node's mount
# pointing at a deleted inode, so the node sees an empty /data even after
# deploy.sh recreates it on the host -- local PVs then fail to mount with
# 'path "/data/db" does not exist'. Recovering needs a node restart.
echo "sudo find ${HOST_MOUNT_ROOT_PATH:?} -mindepth 1 -delete"
sudo find "${HOST_MOUNT_ROOT_PATH:?}" -mindepth 1 -delete

echo
echo "=== Clearing Released PersistentVolumes ==================================="
for pv in $(kubectl get pv -o jsonpath='{range .items[?(@.status.phase=="Released")]}{.metadata.name}{"\n"}{end}' 2>/dev/null); do
  case "$pv" in
    "$RELEASE_NAME"-*)
      echo "Clearing claimRef for $pv"
      kubectl patch pv "$pv" -p '{"spec":{"claimRef":null}}'
      ;;
  esac
done

echo "Persistent volumes cleared"

echo
echo "=== Teardown Complete ======================================================="
echo "All persistent data has been removed."
echo "Run './scripts/cluster.sh down' to delete the cluster."
echo "Run './scripts/cluster.sh up' to create the cluster."
echo "Run './scripts/deploy.sh' to deploy the helm project"
echo
