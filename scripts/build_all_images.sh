#!/usr/bin/env bash

set -euo pipefail

DOCKER_TAG=$1

DOCKER_DIRS=(
  "dagster"
  "webserver"
  "pypipes"
  "github_transfer"
  "uc1"
  "build/alpine"
  "build/kc-init"
)


for dir in "${DOCKER_DIRS[@]}"; do
  if [[ ! -d "$dir" ]]; then
    echo "Skipping '$dir': directory does not exist"
    continue
  fi
  ./scripts/build_image.sh "$dir" "$DOCKER_TAG"
done

echo "Image builds successful!"