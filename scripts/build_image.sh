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

# UPSTREAM_REGISTRY (scripts/sandbox/sandbox.sh sets it to the host's kind registry): reuse an
# image instead of building it. Ours with this tag first, then the upstream's latest.
if [[ -n "${UPSTREAM_REGISTRY:-}" ]]; then
  has_image() {
    curl -fsI -o /dev/null \
      -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
      "http://$1/v2/$2/manifests/$3"
  }
  if has_image "$REGISTRY" "$IMAGE_NAME" "$TAG"; then
    echo "Reusing $IMAGE_REF:$TAG, already in $REGISTRY"
    exit 0
  fi
  if has_image "$UPSTREAM_REGISTRY" "$IMAGE_NAME" latest; then
    echo "Copying $IMAGE_NAME:latest from $UPSTREAM_REGISTRY to $IMAGE_REF:$TAG"
    docker pull "$UPSTREAM_REGISTRY/$IMAGE_NAME:latest"
    docker tag "$UPSTREAM_REGISTRY/$IMAGE_NAME:latest" "$IMAGE_REF:latest"
    docker tag "$UPSTREAM_REGISTRY/$IMAGE_NAME:latest" "$IMAGE_REF:$TAG"
    docker push "$IMAGE_REF:latest"
    [[ "$TAG" == "latest" ]] || docker push "$IMAGE_REF:$TAG"
    exit 0
  fi
fi

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
