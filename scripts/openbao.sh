#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# OpenBao and the External Secrets Operator in the dev cluster (ADR 0031): the dev twin of a site that keeps
# its Secrets in Azure Key Vault. Opt-in; deploy and flux never run it.
#
# Usage:
#   ./scripts/openbao.sh up      # install both, set up Kubernetes auth, write the first user's login from
#                                # .dev.env, and apply site-example/secrets/vault with the OpenBao store
#   ./scripts/openbao.sh status  # the vault's entries and the ExternalSecrets
#   ./scripts/openbao.sh down    # remove the vault files and uninstall both; keycloak-first-user stays
#
# OpenBao runs in dev mode: in memory, unsealed, root token "root". A restart loses its entries: run `up` again.
###############################################################################

COMMAND="${1:-}"

source scripts/load_env.sh

ESO_VERSION=2.15.0
OPENBAO_VERSION=0.30.7
ESO_NS=external-secrets
BAO_NS=openbao
VAULT_DIR=site-example/secrets/vault
KEYCLOAK_NAMESPACE="${KEYCLOAK_NAMESPACE:-keycloak}"
# The ServiceAccount in serviceaccount.yaml, and the OpenBao role in store-openbao.yaml
ESO_SA=fn-external-secrets

bao() {
  kubectl exec -i -n "$BAO_NS" openbao-0 -- env BAO_TOKEN=root bao "$@"
}

# The vault files with the OpenBao store in place of Azure's, in the dev namespaces
vault_files() {
  sed -e "s/namespace: fn$/namespace: $NAMESPACE/" -e "s/namespace: keycloak$/namespace: $KEYCLOAK_NAMESPACE/" \
    "$VAULT_DIR/serviceaccount.yaml" <(echo ---) \
    "$VAULT_DIR/store-openbao.yaml" <(echo ---) \
    "$VAULT_DIR/first-user-from-vault.yaml"
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

    echo "=== Kubernetes auth for $NAMESPACE/$ESO_SA ================================"
    bao auth list | grep -q '^kubernetes/' || bao auth enable kubernetes
    bao write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc:443
    echo 'path "secret/data/*" { capabilities = ["read"] }' | bao policy write "$ESO_SA" -
    bao write "auth/kubernetes/role/$ESO_SA" \
      bound_service_account_names="$ESO_SA" \
      bound_service_account_namespaces="$NAMESPACE" \
      policies="$ESO_SA" ttl=1h

    echo "=== Vault entries from .dev.env ==========================================="
    bao kv put secret/keycloak-first-user \
      EMAIL="$KEYCLOAK_FIRST_USER_EMAIL" PASSWORD="$KEYCLOAK_FIRST_USER_PASSWORD" > /dev/null
    echo "keycloak-first-user: written"

    echo "=== $VAULT_DIR with the OpenBao store ======================================"
    vault_files | kubectl apply -f -
    for ns in "$NAMESPACE" "$KEYCLOAK_NAMESPACE"; do
      kubectl wait externalsecret/keycloak-first-user -n "$ns" --for=condition=Ready --timeout=60s
    done
    ;;
  status)
    bao kv list secret/
    kubectl get clustersecretstores
    kubectl get externalsecrets -A
    ;;
  down)
    # The ExternalSecret owns its Secret: orphan it, so keycloak-first-user stays for deploy.sh's login
    vault_files | kubectl delete --cascade=orphan --ignore-not-found -f - 2>/dev/null || true
    helm uninstall openbao --namespace "$BAO_NS" --ignore-not-found
    helm uninstall external-secrets --namespace "$ESO_NS" --ignore-not-found
    ;;
  *)
    echo "usage: $0 up|status|down" >&2
    exit 2
    ;;
esac
