#!/usr/bin/env bash
set -e

IMAGE_TAG="v5"
IMAGE_NAME="iris-analytics"
CONTAINER_REG_URI="localhost:5001"

# Build the local Docker image
echo "Building image: $IMAGE_NAME:$IMAGE_TAG"
docker build -t $IMAGE_NAME:$IMAGE_TAG --progress=plain .

# Tag the image for the MicroK8s registry
echo "Tagging image -> $CONTAINER_REG_URI/$IMAGE_NAME:$IMAGE_TAG"
docker tag $IMAGE_NAME:$IMAGE_TAG $CONTAINER_REG_URI/$IMAGE_NAME:$IMAGE_TAG

# Push into MicroK8s registry
echo "Pushing image -> $CONTAINER_REG_URI/$IMAGE_NAME:$IMAGE_TAG"
docker push $CONTAINER_REG_URI/$IMAGE_NAME:$IMAGE_TAG
