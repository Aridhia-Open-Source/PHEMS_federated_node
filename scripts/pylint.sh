#!/bin/env bash

set -eu

# User-defined variables
#
PRE_LINT=${PRE_LINT:-"pip3 install --no-cache-dir pipenv && pipenv install --categories \"packages dev-packages\" && pipenv run "} # Bash to run before executing the linter
OUTPUT_DIR=${OUTPUT_DIR:-artifacts} # Path to write the results file in
PROJECT=${PROJECT:-nexus/api} # Directory to lint: nexus/api or dagster

# Internal variables
BUILD_ID=${BUILD_ID:-$(uuidgen)}
# Docker names can't hold the slash in nexus/api
name="${PROJECT//\//-}"
container_name="pylint_${name}_${BUILD_ID}"
# nexus/api keeps the original report name
report_name=$([[ "${PROJECT}" == "nexus/api" ]] && echo "pylint.txt" || echo "pylint-${name}.txt")

set +e
# The dagster lint image is built FROM the local Dagster image, so build that first
if [[ "${PROJECT}" == "dagster" ]]; then
  docker compose -f dagster/docker-compose-tests-ci.yaml build base || exit 1
fi
docker build "${PROJECT}" -f "${PROJECT}/build/test.Dockerfile" -t "${name}_lint"
docker run \
  --volume "$(pwd)":/app:ro \
  --workdir "/app/${PROJECT}" \
  --init \
  -e PYTHONPATH="/app/${PROJECT}" \
  --name "${container_name}" \
  --entrypoint "./pylint-entrypoint.sh" \
  "${name}_lint"
exit_status=$?
set -e
docker cp "${container_name}":/tmp/pylint.txt "${OUTPUT_DIR}/${report_name}"
docker rm "${container_name}"
exit "${exit_status}"

