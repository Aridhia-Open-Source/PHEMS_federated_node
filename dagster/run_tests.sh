#!/bin/bash

is_ci=$1
pytest_args="${2:-.}"

# Each run gets its own compose project (containers, network) so parallel runs
# don't collide.
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-dagster-test-$(uuidgen | cut -c1-8)}"
container="${COMPOSE_PROJECT_NAME}-app"

cleanup() {
    echo "Cleaning up compose resources"
    docker rm -f "$container" > /dev/null 2>&1 || true
    docker compose -f docker-compose-tests-ci.yaml -f docker-compose-tests.yaml down --volumes
}
trap cleanup EXIT

# The test image is built FROM the locally built Dagster image
docker compose -f docker-compose-tests-ci.yaml build base || exit 1

echo "Starting docker compose (project $COMPOSE_PROJECT_NAME)"
if [[ "$is_ci" != "ci" ]]; then
    docker compose -f docker-compose-tests-ci.yaml -f docker-compose-tests.yaml run --build --name "$container" --entrypoint pytest app -x -v $pytest_args
    exit $?
else
    docker compose -f docker-compose-tests-ci.yaml run --build --quiet-pull --name "$container" --entrypoint pytest app -v $pytest_args
    exit $?
fi
