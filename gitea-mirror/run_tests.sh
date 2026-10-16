#!/bin/bash

echo "Setting up docker-compose env vars"
export PGHOST=db
export PGDATABASE=gitea_mirror_test
export PGPORT=5432
export PGUSER=admin
export PGPASSWORD=gitea_mirror_test
export GITEA_MIRROR_DB_USER=$PGUSER
export GITEA_MIRROR_DB_PASSWORD=$PGPASSWORD
export GITEA_MIRROR_DB_NAME=$PGDATABASE
export GITEA_MIRROR_DB_HOST=$PGHOST
export GITEA_MIRROR_DB_PORT=$PGPORT
export PYTHONPATH=/app

is_ci=$1
pytest_args="${2:-.}"

# Each run gets its own compose project (containers, network, volumes) so parallel runs
# don't collide.
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-gm-test-$(uuidgen | cut -c1-8)}"
container="${COMPOSE_PROJECT_NAME}-app"

cleanup() {
    echo "Cleaning up compose resources"
    docker rm -f "$container" > /dev/null 2>&1 || true
    docker compose -f docker-compose-tests-ci.yaml -f docker-compose-tests.yaml down --volumes
}
trap cleanup EXIT

echo "Starting docker compose (project $COMPOSE_PROJECT_NAME)"
if [[ "$is_ci" != "ci" ]]; then
    docker compose -f docker-compose-tests-ci.yaml -f docker-compose-tests.yaml run --build --name "$container" --entrypoint pytest app -x -v $pytest_args
    exit_code=$?
    exit $exit_code
else
    docker compose -f docker-compose-tests-ci.yaml run --build --quiet-pull --name "$container" --entrypoint pytest app -v $pytest_args
    exit_code=$?
    if [[ $exit_code -gt 0 ]]; then
        echo "Something went wrong. Here are some logs"
        docker compose -f docker-compose-tests-ci.yaml logs app
    fi
    exit $exit_code
fi
