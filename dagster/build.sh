#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG="v15"
IMAGE_NAME="dagster-fn"
REGISTRY="localhost:5001"

IMAGE_REF="$REGISTRY/$IMAGE_NAME"

docker build --progress=plain \
  -t "$IMAGE_REF:latest" \
  -t "$IMAGE_REF:$IMAGE_TAG" \
  .

docker push "$IMAGE_REF:latest"
docker push "$IMAGE_REF:$IMAGE_TAG"