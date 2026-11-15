#!/bin/bash
# Run the operator tests in the lint image, with the repo mounted. Optional argument: the pytest path.

set -e

cd "$(dirname "$0")"
docker build . -f build/test.Dockerfile -t nexus-operator_test
docker run --rm --init \
  --volume "$(git rev-parse --show-toplevel)":/app:ro \
  --workdir /app/nexus/operator \
  -e PYTHONPATH=/app/nexus/operator:/app/nexus/client \
  -e PYTHONDONTWRITEBYTECODE=1 \
  nexus-operator_test pytest -v -p no:cacheprovider ${1:-tests}
