#! /usr/bin/env bash

set -euo pipefail

TARGET_DIR=$1
IMAGE_TAG="v1"
IMAGE_NAME="dagster-pipes-$TARGET_DIR"
REGISTRY_URI="localhost:5001"

cd $TARGET_DIR

# Build the local Docker image
echo "Building image: $IMAGE_NAME:$IMAGE_TAG"
docker build -t $IMAGE_NAME:$IMAGE_TAG --progress=plain .

# Tag the image
echo "Tagging image -> $REGISTRY_URI/$IMAGE_NAME:$IMAGE_TAG"
docker tag $IMAGE_NAME:$IMAGE_TAG $REGISTRY_URI/$IMAGE_NAME:$IMAGE_TAG

# Push to local registry
echo "Pushing image -> $REGISTRY_URI/$IMAGE_NAME:$IMAGE_TAG"
docker push $REGISTRY_URI/$IMAGE_NAME:$IMAGE_TAG
