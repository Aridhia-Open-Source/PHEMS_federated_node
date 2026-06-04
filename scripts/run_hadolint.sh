#!/bin/bash

set -e

ARTIFACTS_DIR=artifacts

if [ ! -x "$(which xmlstarlet)" ]; then
  echo "xmlstarlet not found, installing..."
  sudo apt update
  sudo apt install xmlstarlet --no-install-recommends -y
fi

#shellcheck disable=2046
DOCKERFILES=$(find . -type f -name "Dockerfile")

set +e

# Run with readable output
docker run \
  --volume "$(pwd)":/mnt:ro \
  --workdir /mnt \
  --init \
  --rm \
  hadolint/hadolint:latest-alpine hadolint $DOCKERFILES
exit_status=$?

# Generate JUnit XML artifact for CI reporting
docker run \
  --volume "$(pwd)":/mnt:ro \
  --workdir /mnt \
  --init \
  --rm \
  hadolint/hadolint:latest-alpine hadolint -f checkstyle $DOCKERFILES \
  | xmlstarlet tr scripts/checkstyle2junit.xslt > "$ARTIFACTS_DIR"/hadolint.xml

set -e

exit "$exit_status"
