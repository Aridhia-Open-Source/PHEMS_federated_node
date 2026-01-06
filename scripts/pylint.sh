#!/bin/env bash

set -eu

# User-defined variables
#
PRE_LINT=${PRE_LINT:-"pip3 install --no-cache-dir pipenv && pipenv install --categories \"packages dev-packages\" && pipenv run "} # Bash to run before executing the linter
OUTPUT_DIR=${OUTPUT_DIR:-artifacts} # Path to write the results file in

# Internal variables
BUILD_ID=${BUILD_ID:-$(uuidgen)}
container_name="pylint_${BUILD_ID}"

set +e
docker build webserver -f webserver/build/test.Dockerfile -t federated_node_lint
docker run \
  --volume "$(pwd)":/app:ro \
  --workdir /app/webserver \
  --init \
  -e PYTHONPATH=/app/webserver \
  --name "${container_name}" \
  --entrypoint "./pylint-entrypoint.sh" \
  federated_node_lint
exit_status=$?
set -e
docker cp "${container_name}":/tmp/pylint.txt "${OUTPUT_DIR}/pylint.txt"
docker rm "${container_name}"
exit "${exit_status}"

