#!/usr/bin/env bash
# Build the dev images with docker buildx bake and push them to the local registry (tagged latest).
#   scripts/build_images.sh                       the node's images and every experiment's
#   scripts/build_images.sh nexus-api-fn demo-fn  just those bake targets
# The release images are built by `make images-release`, not here.
set -euo pipefail
shopt -s nullglob

cd "$(dirname "$0")/.."

FILES=(
  -f docker-bake.hcl
)
TARGETS=(
  default   # the node's own images, see docker-bake.hcl
)
for file in experiments/*/docker-bake.hcl; do
  # Skip an experiment whose build context is not checked out
  context="$(sed -n 's/^ *context *= *"\(.*\)".*/\1/p' "$file")"
  [[ -d "$context" ]] || continue
  FILES+=(-f "$file")
  # Bake groups of different files do not merge, so `default` holds only the node's images:
  # each experiment's target is named here
  TARGETS+=("$(basename "$(dirname "$file")")-fn")
done

# Named targets replace the full list; every file is still loaded, since a target may be an experiment's
if [[ $# -gt 0 ]]; then
  TARGETS=("$@")
fi

docker buildx bake \
  "${FILES[@]}" \
  "${TARGETS[@]}" \
  --push
