#!/bin/bash

set -e

IMAGE_NAME="helm-unittest-fn"
CONTAINER_NAME="helm-test"

if [[ -z "$(docker ps -a -f "name=$CONTAINER_NAME" --format json | jq length)" ]]; then
  echo "Image missing"
else
   docker rm "$CONTAINER_NAME"
fi
docker build \
  -f build/helm-unittest/Dockerfile \
  . \
  -t "$IMAGE_NAME"

docker run --name "$CONTAINER_NAME" "$IMAGE_NAME"

exit_code=$?

docker rm "$CONTAINER_NAME" -v

exit $exit_code
