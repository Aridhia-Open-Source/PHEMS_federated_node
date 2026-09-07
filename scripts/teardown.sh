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
echo "=== Releasing PVCs held by leftover pods ======================================"
# The Dagster K8sRunLauncher and Pipes create Jobs the release never owned, so
# `helm uninstall` leaves them behind. Their pods keep the kubernetes.io/pvc-protection
# finalizer on every PVC they mount even once Completed or Failed, so the PVC sits in
# Terminating, its PV stays Bound instead of going Released, and the claimRef clearing at
# the end of this script never sees it - which is what leaves the next install with a PV
# bound to a claim that no longer exists.
#
# Holders are matched on referencing a PVC rather than on a name or a label, so run
# workers, pipes pods and anything else mounting a claim are all covered. The owning Job
# is what gets deleted where there is one: deleting only the pod leaves the Job
# controller free to make another.
teardown_namespaces=("$NAMESPACE" "${TASK_NAMESPACE:-}" keycloak)

for ns in "${teardown_namespaces[@]}"; do
  [[ -n "$ns" ]] || continue
  kubectl get namespace "$ns" >/dev/null 2>&1 || continue

  # Every Dagster-launched Job first, whether or not it currently has a pod. A run Job
  # whose pod was already garbage collected holds nothing, but it is still free to create
  # one after the scan below has looked - which would re-block the PVC we just freed.
  kubectl delete job -n "$ns" -l dagster/run-id \
    --ignore-not-found --wait=false >/dev/null 2>&1 || true

  holders=$(kubectl get pods -n "$ns" -o json 2>/dev/null | jq -r '
    .items[]
    | select(any(.spec.volumes[]?; has("persistentVolumeClaim")))
    | (.metadata.ownerReferences[]? | select(.kind == "Job") | "job/" + .name)
      // ("pod/" + .metadata.name)
  ' | sort -u)

  if [[ -z "$holders" ]]; then
    echo "$ns: no leftover pods holding a PVC"
    continue
  fi

  echo "$ns: deleting $(echo "$holders" | wc -l) PVC holder(s)"
  echo "$holders" | sed 's/^/  /'
  # Word splitting is what turns the list into separate arguments here.
  # shellcheck disable=SC2086
  kubectl delete -n "$ns" $holders --ignore-not-found --wait=false >/dev/null
done

# The PVCs were deleted by the uninstall above; they only finish once the last holder is
# gone. Waited on rather than assumed, because the claimRef clearing below reads the PV
# phase and would run too early otherwise.
deadline=$((SECONDS + 120))
while :; do
  terminating=""
  for ns in "${teardown_namespaces[@]}"; do
    [[ -n "$ns" ]] || continue
    kubectl get namespace "$ns" >/dev/null 2>&1 || continue
    terminating+=$(kubectl get pvc -n "$ns" -o json 2>/dev/null | jq -r '
      .items[]
      | select(.metadata.deletionTimestamp)
      | .metadata.namespace + "/" + .metadata.name
    ')$'\n'
  done
  terminating=$(echo "$terminating" | grep -v '^$' || true)

  [[ -z "$terminating" ]] && break

  if (( SECONDS >= deadline )); then
    echo "Still Terminating after 120s:"
    echo "$terminating" | sed 's/^/  /'
    echo "Something outside the namespaces above still mounts them. To find it:"
    echo "  kubectl get pods -A -o json | jq -r '.items[]"
    echo "    | select(any(.spec.volumes[]?; has(\"persistentVolumeClaim\")))"
    echo "    | .metadata.namespace + \"/\" + .metadata.name'"
    break
  fi

  sleep 2
done

echo "PVCs released"

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
echo "=== Removing dataset credential secrets ======================================"
# Written by the webserver through the API when a dataset is registered, so the release
# never owned them and `helm uninstall` leaves them. They then outlive both the dataset
# rows and the roles the wipe above removed, and the passwords they hold are the ones
# task pods authenticate with - so a stale one fails a task run rather than the deploy,
# a long way from the cause.
#
# Matched on the labels the webserver sets, and on the -creds name it derives from the
# dataset host, which is what identifies the ones written before those labels existed.
# Anything Helm manages is left for Helm to remove.
for ns in "${teardown_namespaces[@]}"; do
  [[ -n "$ns" ]] || continue
  kubectl get namespace "$ns" >/dev/null 2>&1 || continue

  stale=$(kubectl get secret -n "$ns" -o json 2>/dev/null | jq -r '
    .items[]
    | select(.metadata.labels["app.kubernetes.io/managed-by"] != "Helm")
    | select(.metadata.labels.type == "database" or (.metadata.name | endswith("-creds")))
    | "secret/" + .metadata.name
  ' | sort -u)

  if [[ -z "$stale" ]]; then
    echo "$ns: no dataset credential secrets left over"
    continue
  fi

  echo "$ns: deleting $(echo "$stale" | wc -l) dataset credential secret(s)"
  echo "$stale" | sed 's/^/  /'
  # shellcheck disable=SC2086
  kubectl delete -n "$ns" $stale --ignore-not-found >/dev/null
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
