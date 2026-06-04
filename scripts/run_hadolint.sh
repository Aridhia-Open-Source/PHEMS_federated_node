#!/bin/bash

set -e

ARTIFACTS_DIR=artifacts

if [ ! -x "$(which xmlstarlet)" ]; then
  echo "xmlstarlet not found, installing..."
  sudo apt update
  sudo apt install xmlstarlet --no-install-recommends -y
fi

#shellcheck disable=2046
DOCKERFILES=$(find . -type f -name "Dockerfile" -not -path "./.*")

set +e

HADOLINT_FLAGS="--config /mnt/.hadolint.yaml"

# Run with readable output
# DL3008 (pin apt versions): ignored — pinned versions disappear from repos on
# security patches, and the base image tag already anchors the Debian release.
#shellcheck disable=2086
docker run \
  --volume "$(pwd)":/mnt:ro \
  --workdir /mnt \
  --init \
  --rm \
  hadolint/hadolint:latest-alpine hadolint $HADOLINT_FLAGS $DOCKERFILES
exit_status=$?

# Generate JUnit XML artifact for CI reporting
#shellcheck disable=2086
docker run \
  --volume "$(pwd)":/mnt:ro \
  --workdir /mnt \
  --init \
  --rm \
  hadolint/hadolint:latest-alpine hadolint -f checkstyle $HADOLINT_FLAGS $DOCKERFILES \
  | xmlstarlet tr scripts/checkstyle2junit.xslt > "$ARTIFACTS_DIR"/hadolint.xml

set -e

exit "$exit_status"
