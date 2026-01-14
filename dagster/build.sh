#!/usr/bin/env bash
set -e

IMAGE_TAG="v5"
IMAGE_NAME="iris-analytics"
REGISTRY_URI="localhost:5001"

# Build the local Docker image
echo "Building image: $IMAGE_NAME:$IMAGE_TAG"
docker build -t $IMAGE_NAME:$IMAGE_TAG --progress=plain .

# Tag the image for the MicroK8s registry
echo "Tagging image -> $CONTAINER_REG_URI/$IMAGE_NAME:$IMAGE_TAG"
docker tag $IMAGE_NAME:$IMAGE_TAG $CONTAINER_REG_URI/$IMAGE_NAME:$IMAGE_TAG
docker image tag $IMAGE_NAME:$IMAGE_TAG $IMAGE_NAME:latest

# Push into MicroK8s registry
echo "Pushing image -> $REGISTRY_URI/$IMAGE_NAME:$IMAGE_TAG"
docker push $REGISTRY_URI/$IMAGE_NAME:$IMAGE_TAG
