#!/usr/bin/env bash
set -euo pipefail

DIR="${1:?Usage: build_image.sh <dir> [tag]}"
TAG="${2:-latest}"
REGISTRY="localhost:5001"

if [[ ! -d "$DIR" ]]; then
  echo "Error: directory '$DIR' does not exist"
  exit 1
fi

BASENAME="$(basename "$DIR")"
IMAGE_NAME="${BASENAME}-fn"
IMAGE_REF="$REGISTRY/$IMAGE_NAME"

cd "$DIR"

echo "Building $IMAGE_REF:$TAG"

# Always build latest
docker build --progress=plain \
  -t "$IMAGE_REF:latest" \
  -t "$IMAGE_REF:$TAG" \
  .

# Always push latest
docker push "$IMAGE_REF:latest"

# Push tag only if distinct
if [[ "$TAG" != "latest" ]]; then
  docker push "$IMAGE_REF:$TAG"
fi
