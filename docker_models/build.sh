#! /usr/bin/env bash

set -e

TARGET_DIR=$1
IMAGE_TAG="v1"
IMAGE_NAME="dagster-pipes-$TARGET_DIR"
REGISTRY_URI="localhost:5001"

cd $TARGET_DIR
echo $PWD
# build and tag the docker image
echo "Building image: $IMAGE_NAME:$IMAGE_TAG"
docker build -t $IMAGE_NAME:$IMAGE_TAG .
docker image tag $IMAGE_NAME:$IMAGE_TAG $IMAGE_NAME:latest

# Push into MicroK8s registry
echo "Pushing image -> $REGISTRY_URI/$IMAGE_NAME:$IMAGE_TAG"
docker push $REGISTRY_URI/$IMAGE_NAME:$IMAGE_TAG
