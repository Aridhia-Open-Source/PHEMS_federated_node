#!/usr/bin/env bash

set -euo pipefail

DOCKER_TAG=$1

DOCKER_DIRS=(
  "dagster"
  "webserver"
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

# nexus/api shares its basename with other dirs, so it gets an explicit image name
./scripts/build_image.sh nexus/api "$DOCKER_TAG" nexus-api-fn

echo "Image builds successful!"