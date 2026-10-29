#!/bin/bash

echo "Setting up docker-compose env vars"
export PGHOST=db
export PGDATABASE=test_app
export PGPORT=5432
export PGUSER=admin
export PGPASSWORD=test_app
# The app builds its URI from BACKEND_DB_*; PG* stay for psql inside the container.
export BACKEND_DB_USER=$PGUSER
export BACKEND_DB_PASSWORD=$PGPASSWORD
export BACKEND_DB_NAME=$PGDATABASE
export KEYCLOAK_URL=http://keycloak:8080
export KEYCLOAK_REALM=FederatedNode
export KEYCLOAK_CLIENT=global
export KEYCLOAK_ADMIN=admin
export KEYCLOAK_ADMIN_PASSWORD=password1
export KEYCLOAK_SERVICE_USER=fn-service
export KEYCLOAK_SERVICE_PASSWORD=servicepass1
export KC_BOOTSTRAP_ADMIN_USERNAME=tmpadmin
export KC_BOOTSTRAP_ADMIN_PASSWORD=password1
export KEYCLOAK_SECRET=qwtirtvJJ4PW4skOlW6Oifk2
export PYTHONPATH=/app
export SECRETS_NAMESPACE=default
export TASK_NAMESPACE=tasks
export KEYCLOAK_NAMESPACE=keycloak
export PUBLIC_URL=localhost:5000

is_ci=$1
pytest_args="${2:-.}"

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
    docker cp "$container":/app/artifacts/coverage.xml ../artifacts/ 2>/dev/null || true
    exit $exit_code
else
    docker compose -f docker-compose-tests-ci.yaml run --build --quiet-pull --name "$container" --entrypoint pytest app -v $pytest_args
    exit_code=$?
    if [[ $exit_code -gt 0 ]]; then
        echo "Something went wrong. Here are some logs"
        docker compose -f docker-compose-tests-ci.yaml logs app
    fi
    docker cp "$container":/app/artifacts/coverage.xml ../artifacts/ 2>/dev/null || true
    exit $exit_code
fi
