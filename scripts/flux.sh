#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Flux in the dev cluster, delivering the node from an independent Gitea site repository (ADR 0031).
# Start Docker Gitea with `mise run gitea-bootstrap`; the application itself is installed only after
# the prepared `demo-install` branch is merged into main.
#
# Usage:
#   ./scripts/flux.sh publish 0.0.1-dev  # package this chart as that version, push it to the kind registry
#   ./scripts/flux.sh up       # install Flux, create fn-site, and push the application as demo-install
#   ./scripts/flux.sh sops-key # make this cluster's age key (once) and load it into Flux, so it decrypts SOPS files
#   ./scripts/flux.sh status   # Flux objects, and the release's helm history
#   ./scripts/flux.sh down     # remove Flux and the fn-site repository; Docker Gitea is managed separately
#   ./scripts/flux.sh check    # fail if Flux manages the release (deploy.sh and teardown.sh call it)
#
# The loop (bump, revert, config edit) is in docs/versions/2.x/docs/GitOps-Delivery.md.
###############################################################################

COMMAND="${1:-}"

source scripts/load_env.sh
source scripts/gitea_lib.sh

SITE_DIR=site-example
SITE_REPO=fn-site
LOCAL_SITE_DIR=.local/fn-site
LOCAL_SITE_URL="${GITEA_LOCAL_URL:-http://localhost:4000}"
HR_NAME=federated-node
# Flux's own objects (the site repository and its Kustomization) live with Flux
FLUX_NS=flux-system
# SOPS: the age key Flux decrypts the site repository's encrypted files with. Its private half stays out of
# git (bootstrap/ is gitignored) and in the cluster as this Secret.
SOPS_SECRET=sops-age
# Docker-backed Gitea joins the kind network as gitea-bootstrap. Override this for a real site.
SITE_URL_IN_CLUSTER="${GITEA_SITE_URL:-http://gitea-bootstrap:3000}/$GITEA_ADMIN_USER/$SITE_REPO.git"

# Is a HelmRelease managing the dev release? Quiet when Flux is not installed.
flux_manages_release() {
  [ -n "$(kubectl get helmreleases.helm.toolkit.fluxcd.io -n "$NAMESPACE" -o name 2>/dev/null)" ]
}

# One age key file per cluster, named by the kubectl context, so a site never loads (or shares) another cluster's
# private key. The dev cluster's is bootstrap/sops/kind-fn.agekey.
age_key_file() {
  local context
  context="$(kubectl config current-context)"
  echo "bootstrap/sops/${context//[^A-Za-z0-9._-]/_}.agekey"
}

# Make this cluster's age key if there is none, and load its private half as the Secret Flux decrypts with
load_sops_key() {
  AGE_KEY_FILE="$(age_key_file)"
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
  age-keygen -y "$(age_key_file)"
}

prepare_kind_storage() {
  while IFS= read -r node; do
    docker exec "$node" mkdir -p /data/db /data/dagster/artifacts
  done < <(kind get nodes --name fn)
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

    prepare_kind_storage
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    for namespace in keycloak fn-operator tasks; do
      kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
    done

    echo
    echo "=== Installing Flux ======================================================"
    flux check --pre
    flux install
    load_sops_key

    echo
    echo "=== Site repository $GITEA_ADMIN_USER/$SITE_REPO =========================="
    gitea_connect
    if [ "$(gitea_ensure_repo "$SITE_REPO")" = created ]; then
      # Seed only the validation workflow on main. The application is installed by the first PR.
      rm -rf "$LOCAL_SITE_DIR"
      mkdir -p "$(dirname "$LOCAL_SITE_DIR")"
      mkdir -p "$LOCAL_SITE_DIR/.gitea" "$LOCAL_SITE_DIR/ci"
      cp -r "$SITE_DIR/.gitea/." "$LOCAL_SITE_DIR/.gitea/"
      cp -r "$SITE_DIR/ci/." "$LOCAL_SITE_DIR/ci/"
      [ ! -e "$SITE_DIR/README.md" ] || cp "$SITE_DIR/README.md" "$LOCAL_SITE_DIR/README.md"
      cat > "$LOCAL_SITE_DIR/kustomization.yaml" <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: []
YAML
      git -C "$LOCAL_SITE_DIR" init -q -b main
      git -C "$LOCAL_SITE_DIR" remote add origin "$LOCAL_SITE_URL/$GITEA_ADMIN_USER/$SITE_REPO.git"
      git -C "$LOCAL_SITE_DIR" add .
      git -C "$LOCAL_SITE_DIR" -c user.name=fn-dev -c user.email=fn-dev@example.org commit -q -m "Site: enable pull request validation"
      gitea_git -C "$LOCAL_SITE_DIR" push -q origin main

      # Prepare the complete application as a candidate branch; merging this PR is the first install.
      git -C "$LOCAL_SITE_DIR" checkout -q -b demo-install
      cp -r "$SITE_DIR"/. "$LOCAL_SITE_DIR"/
      sed -i "s/AGE_PUBLIC_KEY/$(age_public_key)/" "$LOCAL_SITE_DIR"/.sops.yaml
      EMAIL="$KEYCLOAK_FIRST_USER_EMAIL" PASSWORD="$KEYCLOAK_FIRST_USER_PASSWORD" python3 - "$LOCAL_SITE_DIR"/secrets/sops/first-user-secret.yaml <<'PY'
import json
import os
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
for placeholder, variable in (("FIRST_USER_EMAIL", "EMAIL"), ("FIRST_USER_PASSWORD", "PASSWORD")):
    text = text.replace(f": {placeholder}\n", f": {json.dumps(os.environ[variable])}\n")
open(path, "w", encoding="utf-8").write(text)
PY
      sops --config "$LOCAL_SITE_DIR/.sops.yaml" encrypt -i "$LOCAL_SITE_DIR/secrets/sops/first-user-secret.yaml"
      sed -i -e "s|SUPERUSER_USERNAME|${KEYCLOAK_SUPERUSER_USERNAME:-}|" -e "s|SUPERUSER_PASSWORD|${KEYCLOAK_SUPERUSER_PASSWORD:-}|" \
        "$LOCAL_SITE_DIR"/secrets/sops/superuser-secret.yaml
      sops --config "$LOCAL_SITE_DIR/.sops.yaml" encrypt -i "$LOCAL_SITE_DIR/secrets/sops/superuser-secret.yaml"
      git -C "$LOCAL_SITE_DIR" add .
      git -C "$LOCAL_SITE_DIR" -c user.name=fn-dev -c user.email=fn-dev@example.org commit -q -m "Site: install Federated Node through Flux"
      gitea_git -C "$LOCAL_SITE_DIR" push -q -u origin demo-install
      git -C "$LOCAL_SITE_DIR" checkout -q main
      echo "Seeded main and pushed application candidate branch demo-install"
      echo "Local site checkout: $LOCAL_SITE_DIR"
    else
      if [ ! -d "$LOCAL_SITE_DIR/.git" ]; then
        mkdir -p "$(dirname "$LOCAL_SITE_DIR")"
        gitea_git clone -q "$(gitea_repo_url "$SITE_REPO")" "$LOCAL_SITE_DIR"
        git -C "$LOCAL_SITE_DIR" remote set-url origin "$LOCAL_SITE_URL/$GITEA_ADMIN_USER/$SITE_REPO.git"
      fi
      echo "Using local site checkout: $LOCAL_SITE_DIR"
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
      --interval=5s
    flux create kustomization "$SITE_REPO" -n "$FLUX_NS" \
      --source="GitRepository/$SITE_REPO" \
      --path=./ \
      --prune=true \
      --decryption-provider=sops \
      --decryption-secret="$SOPS_SECRET" \
      --interval=5s

    echo
    echo
    echo "=== Waiting for Flux source (up to 5m) ================================"
    kubectl wait "gitrepository/$SITE_REPO" -n "$FLUX_NS" --for=condition=Ready --timeout=5m
    kubectl wait "kustomization/$SITE_REPO" -n "$FLUX_NS" --for=condition=Ready --timeout=5m

    echo
    echo "=== Flux Ready ==========================================================="
    echo "Flux is watching main. Merge the demo-install PR to install $RELEASE_NAME."
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
    flux get sources helm -n "$NAMESPACE" 2>/dev/null || echo "No HelmRepository objects in $NAMESPACE yet"
    flux get sources chart -n "$NAMESPACE" 2>/dev/null || echo "No HelmChart objects in $NAMESPACE yet"
    flux get helmreleases -n "$NAMESPACE" 2>/dev/null || echo "No HelmRelease objects in $NAMESPACE yet"
    echo
    if helm status "$RELEASE_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
      helm history "$RELEASE_NAME" -n "$NAMESPACE" --max 5
    else
      echo "No Helm release $RELEASE_NAME in $NAMESPACE yet"
    fi
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
    echo "Kept local site checkout at $LOCAL_SITE_DIR"

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
