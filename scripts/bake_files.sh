#!/usr/bin/env bash
# The experiments' bake files to give `docker buildx bake` after the root docker-bake.hcl, from the repo root:
#   docker buildx bake -f docker-bake.hcl $(scripts/bake_files.sh) default $(scripts/bake_files.sh targets) --push
# Prints "-f <file>" for each experiments/NAME/docker-bake.hcl whose context exists: UC1's source is a clone
# the repo does not hold. With `targets`, prints those experiments' target names (NAME-fn) instead, since bake
# groups of different files do not merge and `default` holds only the node's own images.
set -euo pipefail

cd "$(dirname "$0")/.."

for file in experiments/*/docker-bake.hcl; do
  context="$(sed -n 's/^ *context *= *"\(.*\)".*/\1/p' "$file")"
  [[ -d "$context" ]] || continue
  name="$(basename "$(dirname "$file")")"
  if [[ "${1:-}" == "targets" ]]; then
    printf '%s-fn ' "$name"
  else
    printf -- '-f %s ' "$file"
  fi
done
