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

# Pinned deliberately. On `latest-alpine` a hadolint release lands mid-sprint and fails an
# unrelated PR with findings nobody introduced - 2.15.0 added DL3064, which broke every
# build at once. Bump this when you want the new rules, and fix them in that commit.
HADOLINT_IMAGE="hadolint/hadolint:v2.15.1-alpine"

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
  "$HADOLINT_IMAGE" hadolint $HADOLINT_FLAGS $DOCKERFILES
exit_status=$?

# Generate JUnit XML artifact for CI reporting
#shellcheck disable=2086
docker run \
  --volume "$(pwd)":/mnt:ro \
  --workdir /mnt \
  --init \
  --rm \
  "$HADOLINT_IMAGE" hadolint -f checkstyle $HADOLINT_FLAGS $DOCKERFILES \
  | xmlstarlet tr scripts/checkstyle2junit.xslt > "$ARTIFACTS_DIR"/hadolint.xml

set -e

exit "$exit_status"
