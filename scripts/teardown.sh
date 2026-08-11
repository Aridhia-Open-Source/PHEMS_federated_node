#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Teardown - Completely removes deployment and persistent data
###############################################################################

source .dev.env

FN_DATA_DIR="${FN_DATA_DIR:-$HOME/.fn/data}"

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
echo "=== Clearing local PV data =================================================="
# Before the password secrets below, deliberately: Postgres only reads
# POSTGRES_PASSWORD when initdb creates the data directory, so data that outlives its
# password breaks the next install. If this step fails, the passwords are still there.
#
# Deleted from inside the node rather than from the host, because these files belong to
# the uids the containers ran as (postgres is 70) and the host user cannot always
# remove them - which is what used to make this step need sudo.
if kubectl get nodes >/dev/null 2>&1; then
  echo "wiping /data in the node ($FN_DATA_DIR on the host)"
  kubectl delete pod fn-data-wipe --ignore-not-found >/dev/null 2>&1
  kubectl run fn-data-wipe --rm -i --restart=Never --image=busybox:1.36 --quiet \
    --overrides='{"spec":{"containers":[{"name":"fn-data-wipe","image":"busybox:1.36",
      "command":["sh","-c","rm -rf /host/* /host/.[!.]* 2>/dev/null; echo remaining entries: $(ls -A /host | wc -l)"],
      "securityContext":{"runAsUser":0},
      "volumeMounts":[{"name":"host","mountPath":"/host"}]}],
      "volumes":[{"name":"host","hostPath":{"path":"/data"}}]}}'
else
  echo "No cluster reachable, so nothing was wiped. $FN_DATA_DIR is still on disk:"
  echo "delete it before reinstalling, or keep the password secrets that go with it."
  exit 1
fi

echo
echo "=== Removing chart-generated password secrets ================================"
# Hook resources, so `helm uninstall` leaves them behind.
for ns in "$NAMESPACE" keycloak; do
  kubectl delete secret -n "$ns" -l federatednode.com/generated-password=true \
    --ignore-not-found 2>/dev/null || true
done

# Hook Jobs are untracked too.
for ns in "$NAMESPACE" keycloak; do
  kubectl delete job -n "$ns" backend-db-init keycloak-db-init dagster-db-init db-datasets-init \
    --ignore-not-found 2>/dev/null || true
done

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
