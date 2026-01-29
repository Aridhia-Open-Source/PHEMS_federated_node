#!/usr/bin/env bash

set -euo pipefail

NAMESPACE="fn"
RELEASE_NAME="fn-dev"
VALUES_FILE="example.values.yaml.yaml"

set -euo pipefail

cd k8s/federated-node

kubectl config set-context \
  --current --namespace="$NAMESPACE"

helm upgrade \
  --install "$RELEASE_NAME" . \
  -f "$VALUES_FILE" \
  --timeout 30m
