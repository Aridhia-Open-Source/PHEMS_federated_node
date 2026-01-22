#!/usr/bin/env bash

set -euo pipefail

NAMESPACE="fn"
RELEASE_NAME="fn-dev"
VALUES_FILE=".values/dev.values.yaml"
KIND_CONFIG_FILE=".kind/kind-config.yaml"
DB_SECRET_KEY="local-db-secret"

set -euo pipefail

cd k8s/federated-node

helm upgrade \
  --install "$RELEASE_NAME" . \
  -f "$VALUES_FILE" \
  --timeout 30m