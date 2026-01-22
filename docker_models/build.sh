#! /usr/bin/env bash
set -euo pipefail

TARGET_DIR=$1

IMAGE_TAG="v7"
IMAGE_NAME="dagster-pipes-$TARGET_DIR"
REGISTRY="localhost:5001"
IMAGE_REF="$REGISTRY/$IMAGE_NAME"

cd $TARGET_DIR

docker build --progress=plain \
  -t "$IMAGE_REF:latest" \
  -t "$IMAGE_REF:$IMAGE_TAG" \
  .

docker push "$IMAGE_REF:latest"
docker push "$IMAGE_REF:$IMAGE_TAG"