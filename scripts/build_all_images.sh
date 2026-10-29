#!/usr/bin/env bash

set -euo pipefail

DOCKER_TAG=$1

DOCKER_DIRS=(
  "dagster"
  "pypipes"
  "uc1"
  "build/alpine"
  "build/kc-init"
  "build/keycloak"
)


for dir in "${DOCKER_DIRS[@]}"; do
  if [[ ! -d "$dir" ]]; then
    echo "Skipping '$dir': directory does not exist"
    continue
  fi
  ./scripts/build_image.sh "$dir" "$DOCKER_TAG"
done

# nexus/api and nexus/ui share basenames with other dirs, so they get explicit image names
./scripts/build_image.sh nexus/api "$DOCKER_TAG" nexus-api-fn
./scripts/build_image.sh nexus/ui "$DOCKER_TAG" nexus-ui-fn

echo "Image builds successful!"