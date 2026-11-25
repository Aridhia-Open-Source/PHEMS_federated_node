#!/bin/bash

echo "Setting up docker-compose env vars"
export PGHOST=db
export PGDATABASE=test_app
export PGPORT=5432
export PGUSER=admin
export PGPASSWORD=test_app
# PG* remain available to PostgreSQL tools inside the container.
export DATABASE_HOST="$PGHOST" DATABASE_PORT="$PGPORT" DATABASE_NAME="$PGDATABASE"
export DATABASE_USER="$PGUSER" DATABASE_PASSWORD="$PGPASSWORD"
export SERVICES_KEYCLOAK_URL=http://keycloak:8080 SERVICES_KEYCLOAK_REALM=FederatedNode
export SERVICES_KEYCLOAK_CLIENT=global SERVICES_KEYCLOAK_ADMIN=admin
export SERVICES_KEYCLOAK_SERVICE_USER=fn-service SERVICES_KEYCLOAK_SERVICE_PASSWORD=servicepass1
export SERVICES_KEYCLOAK_SECRET=qwtirtvJJ4PW4skOlW6Oifk2 SERVICES_DAGSTER_URI=http://dagster:3000
export PYTHONPATH=/app
export NAMESPACES_SECRETS=default NAMESPACES_TASKS=tasks NODE_HOSTNAME=localhost:5000
# The chart's taskCompute values, what a spec's compute is checked against
export TASKS_LIMITS_MAX_CPU=4 TASKS_LIMITS_MAX_MEMORY=16Gi
export TASKS_LIMITS_DEFAULT_LIMIT_CPU=2 TASKS_LIMITS_DEFAULT_LIMIT_MEMORY=4Gi

is_ci=$1
pytest_args="${2:-.}"
# pytest-xdist workers, each with its own database (conftest.py); NEXUS_TEST_WORKERS=0 runs serially.
pytest_args="-n ${NEXUS_TEST_WORKERS:-auto} $pytest_args"

# Each run gets its own compose project (containers, network, volumes) so parallel runs
# don't collide.
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-fn-test-$(uuidgen | cut -c1-8)}"
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
    docker cp "$container":/app/artifacts/coverage.xml ../../artifacts/ 2>/dev/null || true
    exit $exit_code
else
    docker compose -f docker-compose-tests-ci.yaml run --build --quiet-pull --name "$container" --entrypoint pytest app -v $pytest_args
    exit_code=$?
    if [[ $exit_code -gt 0 ]]; then
        echo "Something went wrong. Here are some logs"
        docker compose -f docker-compose-tests-ci.yaml logs app
    fi
    docker cp "$container":/app/artifacts/coverage.xml ../../artifacts/ 2>/dev/null || true
    exit $exit_code
fi
