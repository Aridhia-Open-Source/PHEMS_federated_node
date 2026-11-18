#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# OpenBao and the External Secrets Operator in the dev cluster (ADR 0031): the secret store the chart's
# externalSecrets values read in dev. Sites use Azure Key Vault instead.
#
# Usage:
#   ./scripts/openbao.sh up       # install or upgrade both, set up Kubernetes auth, seed the dev values
#   ./scripts/openbao.sh status   # the store's secrets and the ExternalSecrets in the operator namespace
#   ./scripts/openbao.sh down     # uninstall both
#
# OpenBao runs in dev mode: in memory, unsealed, root token "root". A restart loses everything, so run
# `up` again (deploy.sh does, on every deploy).
###############################################################################

COMMAND="${1:-}"

source .dev.env

ESO_VERSION=2.15.0
OPENBAO_VERSION=0.30.7
ESO_NS=external-secrets
BAO_NS=openbao
OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-fn-operator}"
# externalSecrets.serviceAccount.name and externalSecrets.openbao.role in the chart's values
ESO_SA=fn-external-secrets

# Dev secrets: remote name, one value each. Seeded only when missing, so a value stays across reruns
# while the pod lives.
DEV_SECRETS=(dev-example-token)

bao() {
  kubectl exec -n "$BAO_NS" openbao-0 -- env BAO_TOKEN=root bao "$@"
}

case "$COMMAND" in
  up)
    echo "=== External Secrets Operator $ESO_VERSION ================================"
    helm upgrade --install external-secrets external-secrets \
      --repo https://charts.external-secrets.io --version "$ESO_VERSION" \
      --namespace "$ESO_NS" --create-namespace --wait

    echo "=== OpenBao $OPENBAO_VERSION (dev mode) ===================================="
    helm upgrade --install openbao openbao \
      --repo https://openbao.github.io/openbao-helm --version "$OPENBAO_VERSION" \
      --namespace "$BAO_NS" --create-namespace \
      --set server.dev.enabled=true \
      --set server.dev.devRootToken=root \
      --set injector.enabled=false \
      --set server.updateStrategyType=RollingUpdate
    kubectl rollout status statefulset/openbao -n "$BAO_NS" --timeout=180s

    echo "=== Kubernetes auth for $OPERATOR_NAMESPACE/$ESO_SA ========================"
    bao auth list | grep -q '^kubernetes/' || bao auth enable kubernetes
    bao write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc:443
    echo 'path "secret/data/*" { capabilities = ["read"] }' \
      | kubectl exec -i -n "$BAO_NS" openbao-0 -- env BAO_TOKEN=root bao policy write "$ESO_SA" -
    bao write "auth/kubernetes/role/$ESO_SA" \
      bound_service_account_names="$ESO_SA" \
      bound_service_account_namespaces="$OPERATOR_NAMESPACE" \
      policies="$ESO_SA" ttl=1h

    echo "=== Seeding dev secrets ================================================="
    for name in "${DEV_SECRETS[@]}"; do
      if bao kv get "secret/$name" > /dev/null 2>&1; then
        echo "$name: kept"
      else
        bao kv put "secret/$name" value="$(openssl rand -hex 16)" > /dev/null
        echo "$name: seeded"
      fi
    done
    ;;
  status)
    bao kv list secret/
    kubectl get secretstores,externalsecrets -n "$OPERATOR_NAMESPACE"
    ;;
  down)
    helm uninstall openbao --namespace "$BAO_NS" --ignore-not-found
    helm uninstall external-secrets --namespace "$ESO_NS" --ignore-not-found
    ;;
  *)
    echo "usage: $0 up|status|down" >&2
    exit 2
    ;;
esac
