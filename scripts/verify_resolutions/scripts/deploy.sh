#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Helm Deployment - Sets up namespaces, secrets, and deploys Helm release.
# Safe to rerun: it upgrades the release and restarts the app pods, so new images
# (tagged latest) are picked up. There is no separate upgrade script.
###############################################################################

source scripts/load_env.sh
export CUSTOM_CA_FILE   # build_images.sh passes it to image builds

# generated.values.yaml (scripts/configure.sh: the chart's proxy and customCA) goes
# first, so what you set in $VALUES_FILE wins.
VALUES_ARGS=(-f "$VALUES_FILE")
if [ -f k8s/federated-node/generated.values.yaml ]; then
  VALUES_ARGS=(-f generated.values.yaml "${VALUES_ARGS[@]}")
fi

# Flux would put its own version back: the release is either Flux's or deploy's
./scripts/flux.sh check
./scripts/deploy_owner.sh claim

echo
echo "=== Validating Helm templates ==========================================="

# charts/ is gitignored: build the subcharts so a fresh checkout deploys with no extra step
mise run helm deps
(cd k8s/federated-node && helm template "$RELEASE_NAME" . "${VALUES_ARGS[@]}" --namespace "$NAMESPACE" > /dev/null)

# Host directory backing the cluster's local PVs. cluster.sh bind-mounts it to /data
# in the kind node, which is what the chart's storage.local.* values point at. Under
# $HOME so none of this needs sudo.
FN_DATA_DIR="${FN_DATA_DIR:-$HOME/.fn/data}"

HOST_MOUNT_PATHS=(
  "$FN_DATA_DIR/db"
  "$FN_DATA_DIR/dagster/artifacts"
  "$FN_DATA_DIR/gitea"
)

echo
echo "=== Terminating tilt sessions =================================================="

# Tilt injects a `command` the chart does not manage, so Helm's three-way merge keeps it
# while resetting the image, and the pod then dies on a missing /tilt-restart-wrapper.

if command -v tilt &> /dev/null; then
  if pgrep -f "tilt up" > /dev/null; then
    tilt down
    pkill -f "tilt up"
    echo "Terminated tilt session"
  else
    echo "No tilt sessions found"
  fi
fi

# A Tilt session that ended without `tilt down` leaves that command behind too.
for d in $(kubectl get deployments -n "$NAMESPACE" -o name 2>/dev/null); do
  if [ "$(kubectl get "$d" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].command[0]}')" = /tilt-restart-wrapper ]; then
    echo "Removing Tilt's command from $d"
    kubectl patch "$d" -n "$NAMESPACE" --type json -p '[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]'
  fi
done

echo
echo "=== Reconciling PersistentVolumes ======================================"

if [ ! -d "$FN_DATA_DIR" ]; then
  echo "$FN_DATA_DIR does not exist - run mise run cluster up first, since the"
  echo "bind mount into the kind node is set when the cluster is created." >&2
  exit 1
fi

for path in "${HOST_MOUNT_PATHS[@]}"; do
  echo "mkdir $path"
  mkdir -p "$path"
  # The containers that write here run as their own uids (postgres is 70), so a directory
  # they are about to initialise has to be world-writable first.
  #
  # Only while we still own it, though. initdb takes ownership of PGDATA and tightens it to
  # 0700 - Postgres refuses to start on a group- or world-accessible data directory - so on
  # any later run this chmod is both impossible (the directory now belongs to uid 70 and we
  # are not root) and wrong (it would put PGDATA back into a state Postgres rejects). Under
  # `set -e` that failure aborted the deploy, so `mise run deploy` only ever worked once per
  # fresh data directory.
  #
  # Tested with -O rather than emptiness: a 0700 directory owned by another uid is one we
  # cannot even list, so an `ls` test reports it empty and chmods it regardless.
  if [ -O "$path" ]; then
    chmod 777 "$path"
  else
    echo "  owned by uid $(stat -c %u "$path"), which initialised it - leaving it alone"
  fi
done

echo
echo "=== Building Docker Images(s) ========================================"

scripts/build_images.sh

echo
echo "=== Creating Namespaces =================================================="
# The chart creates no namespaces here (global.createNamespaces=false below): the Secrets read
# in the Keycloak namespace go in before the release, as Flux does on a site.
KEYCLOAK_NAMESPACE="${KEYCLOAK_NAMESPACE:-keycloak}"
TASK_NAMESPACE="${TASK_NAMESPACE:-tasks}"
# The operator's own namespace, and experiments for its Role there (dev values operator.watchNamespaces)
OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-fn-operator}"

# A release from before the switch owns them, and the upgrade below would delete them.
if helm get manifest "$RELEASE_NAME" --namespace "$NAMESPACE" 2>/dev/null | grep -q '^kind: Namespace'; then
  echo "Release $RELEASE_NAME still creates its namespaces. Run mise run teardown once, then deploy." >&2
  exit 1
fi

for ns in "$NAMESPACE" "$KEYCLOAK_NAMESPACE" "$TASK_NAMESPACE" "$OPERATOR_NAMESPACE" experiments; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f -
done

echo
echo "=== Creating externally-supplied secrets ================================="
# Only what the chart cannot invent: every database password is generated by its
# pre-install hooks and reused on every upgrade.
# Read by the realm controller in the Keycloak namespace.
kubectl create secret generic keycloak-first-user \
  --from-literal=PASSWORD="$KEYCLOAK_FIRST_USER_PASSWORD" \
  --from-literal=EMAIL="$KEYCLOAK_FIRST_USER_EMAIL" \
  --dry-run=client -o yaml -n "$KEYCLOAK_NAMESPACE" | kubectl apply -f - -n "$KEYCLOAK_NAMESPACE"

kubectl create secret generic keycloak-superuser \
  --from-literal=USERNAME="${KEYCLOAK_SUPERUSER_USERNAME:-}" \
  --from-literal=PASSWORD="${KEYCLOAK_SUPERUSER_PASSWORD:-}" \
  --dry-run=client -o yaml -n "$KEYCLOAK_NAMESPACE" | kubectl apply -f - -n "$KEYCLOAK_NAMESPACE"

# An external Postgres has an admin password the chart cannot generate.
if [ "${POSTGRES_EXTERNAL:-false}" = "true" ]; then
  kubectl create secret generic postgres-superuser \
    --from-literal=password="${POSTGRES_PASSWORD:?POSTGRES_EXTERNAL is set, so POSTGRES_PASSWORD is required}" \
    --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"
fi

# CUSTOM_CA_FILE (optional): a CA the release trusts for outbound TLS. See custom_ca.sh.
source ./scripts/custom_ca.sh
custom_ca_prepare

echo
echo "=== Applying CRDs ======================================================="
# Helm installs the chart's crds/ on a first install but never upgrades them (ADR 0032). The chart's
# pre-upgrade hook applies them on upgrade too.
kubectl apply -f k8s/federated-node/crds/

echo
echo "=== Deploying Helm Release =============================================="

# A first deploy has no pods running old images, so only a rerun needs the restart below.
RELEASE_EXISTS=false
if helm status "$RELEASE_NAME" --namespace "$NAMESPACE" > /dev/null 2>&1; then
  RELEASE_EXISTS=true
fi

cd k8s/federated-node

echo "Helm command:"
echo "  helm upgrade --install $RELEASE_NAME . ${VALUES_ARGS[*]} --timeout 30m --namespace $NAMESPACE --debug"
echo

helm upgrade --install "$RELEASE_NAME" . \
  "${VALUES_ARGS[@]}" \
  --timeout 30m \
  --set "firstUserSecret.email=$KEYCLOAK_FIRST_USER_EMAIL" \
  --set global.createNamespaces=false \
  ${CUSTOM_CA_ARGS[@]+"${CUSTOM_CA_ARGS[@]}"} \
  --namespace "$NAMESPACE" \
  --debug

cd - > /dev/null

# The image tag is latest, so Helm sees no change: restart the app deployments to pick up
# a new build. Only these, not Keycloak and the Postgres instances too.
if [ "$RELEASE_EXISTS" = "true" ]; then
  echo
  echo "=== Restarting the app deployments ======================================"
  kubectl rollout restart -n "$NAMESPACE" \
    deployment/nexus-api \
    "deployment/${RELEASE_NAME}-${DAGSTER_USER_DEPLOYMENT:-dagster-fn}" \
    "deployment/${RELEASE_NAME}-dagster-daemon" \
    "deployment/${RELEASE_NAME}-dagster-webserver"
  # Only with operator.enabled. It runs in its own namespace (global.namespaces.operator).
  OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-fn-operator}"
  if kubectl get deployment nexus-operator -n "$OPERATOR_NAMESPACE" > /dev/null 2>&1; then
    kubectl rollout restart -n "$OPERATOR_NAMESPACE" deployment/nexus-operator
  fi
fi

kubectl config set-context \
  --current --namespace="$NAMESPACE"

echo
echo "=== Experiments Release ================================================="
# The demo and experiment databases, in their own release so they outlive a teardown
fncli experiment deploy

echo
echo "=== Helm Deployment Complete ==========================================="
echo "Namespace: $NAMESPACE"
echo "Release: $RELEASE_NAME"
echo
echo "Chart-generated database passwords:"
kubectl get secret -n "$NAMESPACE" -l federatednode.com/generated-password=true \
  -o go-template='{{range .items}}  {{printf "%-26s" .metadata.name}}{{range $k, $v := .data}}{{$k}}={{$v | base64decode}}{{end}}{{"\n"}}{{end}}'
echo
echo "Watch pods with:"
echo "  kubectl get pods -n $NAMESPACE -w"
echo
