#!/usr/bin/env bash
set -euo pipefail

DOCKER_DIRS=(
  "dagster"
  "webserver"
  "github_transfer"
)

DOCKER_TAG=$1

for dir in "${DOCKER_DIRS[@]}"; do
  ./scripts/build_image.sh "$dir" "$DOCKER_TAG"
done


echo "Image builds successful!"