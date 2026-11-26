#!/usr/bin/env bash
# Installs the pinned tools ci/validate.sh needs into .ci-bin/ (linux amd64), with curl only, so every CI
# system (GitHub Actions, Azure DevOps, Gitea Actions) runs the same versions without marketplace actions.
# Prints the bin directory; the pipeline adds it to PATH.
set -euo pipefail

HELM_VERSION=v3.16.4
KUSTOMIZE_VERSION=v5.5.0
YQ_VERSION=v4.44.6

BIN_DIR="${BIN_DIR:-$PWD/.ci-bin}"
mkdir -p "$BIN_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" | tar -xz -C "$TMP"
mv "$TMP/linux-amd64/helm" "$BIN_DIR/helm"

curl -fsSL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/kustomize_${KUSTOMIZE_VERSION}_linux_amd64.tar.gz" \
  | tar -xz -C "$BIN_DIR" kustomize

curl -fsSL -o "$BIN_DIR/yq" "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_amd64"
chmod +x "$BIN_DIR/helm" "$BIN_DIR/kustomize" "$BIN_DIR/yq"

echo "$BIN_DIR"
