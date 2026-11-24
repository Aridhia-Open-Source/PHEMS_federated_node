#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Flux in the dev cluster, delivering the node from a test site repository (ADR 0031).
# Needs a node from `mise run deploy` (Gitea, which hosts the site repository, is part of it)
# and the chart version site-example pins, in the kind registry (`publish`).
#
# Usage:
#   ./scripts/flux.sh publish 0.0.1-dev  # package this chart as that version, push it to the kind registry
#   ./scripts/flux.sh up       # install Flux, push site-example/ to Gitea as fn-site, let Flux adopt the release
#   ./scripts/flux.sh sops-key # make the dev age key (once) and load it into Flux, so it decrypts SOPS files
#   ./scripts/flux.sh status   # Flux objects, and the release's helm history
#   ./scripts/flux.sh down     # remove Flux and the fn-site repository; the release stays, deploy works again
#   ./scripts/flux.sh check    # fail if Flux manages the release (deploy.sh and teardown.sh call it)
#
# The loop (bump, revert, config edit) is in docs/versions/2.x/docs/GitOps-Delivery.md.
###############################################################################

COMMAND="${1:-}"

source scripts/load_env.sh
source scripts/gitea_lib.sh

SITE_DIR=site-example
SITE_REPO=fn-site
HR_NAME=federated-node
# Flux's own objects (the site repository and its Kustomization) live with Flux
FLUX_NS=flux-system
# SOPS: the age key Flux decrypts the site repository's encrypted files with. Its private half stays out of
# git (bootstrap/ is gitignored) and in the cluster as this Secret.
AGE_KEY_FILE=bootstrap/sops/age.agekey
SOPS_SECRET=sops-age
SITE_URL_IN_CLUSTER="http://gitea.$NAMESPACE.svc:4000/$GITEA_ADMIN_USER/$SITE_REPO.git"

# Is a HelmRelease managing the dev release? Quiet when Flux is not installed.
flux_manages_release() {
  [ -n "$(kubectl get helmreleases.helm.toolkit.fluxcd.io -n "$NAMESPACE" -o name 2>/dev/null)" ]
}

# Make the age key if there is none, and load its private half as the Secret Flux decrypts with
load_sops_key() {
  if [ ! -f "$AGE_KEY_FILE" ]; then
    mkdir -p "$(dirname "$AGE_KEY_FILE")"
    age-keygen -o "$AGE_KEY_FILE"
  fi
  kubectl create secret generic "$SOPS_SECRET" -n "$FLUX_NS" \
    --from-file=age.agekey="$AGE_KEY_FILE" \
    --dry-run=client -o yaml | kubectl apply -f -
  echo "Age key $AGE_KEY_FILE loaded as $FLUX_NS/$SOPS_SECRET, public key $(age_public_key)"
}

age_public_key() {
  age-keygen -y "$AGE_KEY_FILE"
}

case "$COMMAND" in
  ###############################################################################
  # PUBLISH
  ###############################################################################
  publish)
    # The dev stand-in for the chart a v* tag publishes to ghcr.io (.github/workflows/build.yml)
    VERSION="${2:?usage: $0 publish VERSION}"
    DIST="$(mktemp -d)"
    trap 'rm -rf "$DIST"' EXIT
    (cd k8s/federated-node && { helm dependency build || helm dependency update; })
    helm package k8s/federated-node --version "$VERSION" --app-version "$VERSION" -d "$DIST"
    helm push "$DIST/federated-node-$VERSION.tgz" oci://localhost:5001/charts --plain-http
    ;;

  ###############################################################################
  # UP
  ###############################################################################
  up)
    # site-example names the release and namespace; they must be the ones deploy.sh used
    if ! grep -q "releaseName: $RELEASE_NAME\$" "$SITE_DIR/helmrelease.yaml" \
      || ! grep -q "namespace: $NAMESPACE\$" "$SITE_DIR/helmrelease.yaml"; then
      echo "$SITE_DIR/helmrelease.yaml is for release fn-dev in namespace fn, .dev.env has $RELEASE_NAME in $NAMESPACE" >&2
      exit 1
    fi

    ./scripts/deploy_owner.sh claim

    if ! helm status "$RELEASE_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
      echo "No release $RELEASE_NAME in $NAMESPACE: run mise run deploy first (Gitea is part of it)" >&2
      exit 1
    fi

    echo
    echo "=== Installing Flux ======================================================"
    flux check --pre
    flux install
    load_sops_key

    echo
    echo "=== Site repository $GITEA_ADMIN_USER/$SITE_REPO =========================="
    gitea_connect
    if [ "$(gitea_ensure_repo "$SITE_REPO")" = created ]; then
      # A fresh history: the site repository is the site's, not a copy of this one
      SEED="$(mktemp -d)"
      trap 'rm -rf "$SEED"; kill "${GITEA_PF_PID:-}" 2>/dev/null || true' EXIT
      cp "$SITE_DIR"/*.yaml "$SITE_DIR"/.sops.yaml "$SEED"/
      # Encrypt the example Secret for this cluster's age key, as a site does before it commits one
      sed -i "s/AGE_PUBLIC_KEY/$(age_public_key)/" "$SEED"/.sops.yaml
      # The first user's login from .dev.env (scripts/load_env.sh), as a site writes its own
      sed -i -e "s|FIRST_USER_EMAIL|$KEYCLOAK_FIRST_USER_EMAIL|" -e "s|FIRST_USER_PASSWORD|$KEYCLOAK_FIRST_USER_PASSWORD|" \
        "$SEED"/first-user-secret.yaml
      # From the repo root, so a mise shim still finds the sops version mise.toml pins
      sops --config "$SEED/.sops.yaml" encrypt -i "$SEED/first-user-secret.yaml"
      git -C "$SEED" init -q -b main
      git -C "$SEED" add .
      git -C "$SEED" -c user.name=fn-dev -c user.email=fn-dev@example.org commit -q -m "Site: node pinned to its first release"
      gitea_git -C "$SEED" push -q "$(gitea_repo_url "$SITE_REPO")" main
      echo "Pushed $SITE_DIR/ as $GITEA_URL/$GITEA_ADMIN_USER/$SITE_REPO"
    else
      echo "Already there (a mirror from mise run mirror-to-gitea, or an earlier up), left as it is (mise run flux down deletes it)"
    fi

    echo
    echo "=== Pointing Flux at the site repository ================================"
    flux create secret git "$SITE_REPO-auth" -n "$FLUX_NS" \
      --url="$SITE_URL_IN_CLUSTER" \
      --username="$GITEA_ADMIN_USER" \
      --password="$GITEA_ADMIN_PASSWORD"
    flux create source git "$SITE_REPO" -n "$FLUX_NS" \
      --url="$SITE_URL_IN_CLUSTER" \
      --branch=main \
      --secret-ref="$SITE_REPO-auth" \
      --interval=1m
    flux create kustomization "$SITE_REPO" -n "$FLUX_NS" \
      --source="GitRepository/$SITE_REPO" \
      --path=./ \
      --prune=true \
      --decryption-provider=sops \
      --decryption-secret="$SOPS_SECRET" \
      --interval=1m

    echo
    echo "=== Waiting for Flux to adopt the release (up to 30m) ===================="
    kubectl wait "helmrelease/$HR_NAME" -n "$NAMESPACE" --for=condition=Ready --timeout=30m
    flux get helmreleases -n "$NAMESPACE"
    helm history "$RELEASE_NAME" -n "$NAMESPACE" --max 5

    echo
    echo "=== Flux Ready ==========================================================="
    echo "Flux now owns $RELEASE_NAME: mise run deploy and teardown refuse until mise run flux down."
    echo "Site repository: $GITEA_URL/$GITEA_ADMIN_USER/$SITE_REPO"
    echo "The loop: docs/versions/2.x/docs/GitOps-Delivery.md"
    ;;

  ###############################################################################
  # SOPS-KEY
  ###############################################################################
  sops-key)
    load_sops_key
    ;;

  ###############################################################################
  # STATUS
  ###############################################################################
  status)
    flux get sources git -n "$FLUX_NS"
    flux get kustomizations -n "$FLUX_NS"
    flux get sources helm -n "$NAMESPACE"
    flux get sources chart -n "$NAMESPACE"
    flux get helmreleases -n "$NAMESPACE"
    echo
    helm history "$RELEASE_NAME" -n "$NAMESPACE" --max 5
    ;;

  ###############################################################################
  # DOWN
  ###############################################################################
  down)
    ./scripts/deploy_owner.sh check

    echo "=== Removing Flux ========================================================"
    # flux uninstall drops the finalizers before it deletes the Flux objects, so the Helm release
    # and everything it made stay. Suspending first stops a reconcile starting meanwhile.
    flux suspend helmrelease "$HR_NAME" -n "$NAMESPACE" 2>/dev/null || true
    flux suspend kustomization "$SITE_REPO" -n "$FLUX_NS" 2>/dev/null || true
    flux uninstall --silent
    kubectl delete configmap -n "$NAMESPACE" -l "kustomize.toolkit.fluxcd.io/name=$SITE_REPO" --ignore-not-found

    echo
    echo "=== Deleting the site repository ========================================="
    gitea_connect
    gitea_api DELETE "/repos/$GITEA_ADMIN_USER/$SITE_REPO" >/dev/null 2>&1 || true
    echo "Deleted $GITEA_ADMIN_USER/$SITE_REPO (if it was there)"

    echo
    echo "Release $RELEASE_NAME kept at its current version; mise run deploy takes it back to the dev images."
    ;;

  ###############################################################################
  # CHECK
  ###############################################################################
  check)
    if flux_manages_release; then
      echo "Flux manages the release in $NAMESPACE: run mise run flux down first, or it puts the release back." >&2
      exit 1
    fi
    ;;

  *)
    echo "usage: $0 publish VERSION|up|sops-key|status|down|check" >&2
    exit 2
    ;;
esac
