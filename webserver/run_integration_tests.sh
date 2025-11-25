#!/bin/bash

echo "Setting up docker-compose env vars"
export PGHOST=db
export PGDATABASE=test_app
export PGPORT=5432
export PGUSER=admin
export PGPASSWORD=test_app
export KEYCLOAK_URL=http://keycloak:8080
export KEYCLOAK_REALM=FederatedNode
export KEYCLOAK_CLIENT=global
export KEYCLOAK_ADMIN=admin
export KEYCLOAK_ADMIN_PASSWORD=password1
export KEYCLOAK_GLOBAL_CLIENT_SECRET=qwtirtvJJ4PW4skOlW6Oifk2
export PYTHONPATH=/app
export RESULTS_PATH=/tmp/results
export TASK_POD_RESULTS_PATH=/mnt/data
export DEFAULT_NAMESPACE=default
export TASK_NAMESPACE=tasks
export KEYCLOAK_NAMESPACE=keycloak
export CLEANUP_AFTER_DAYS=1
export PUBLIC_URL=localhost:5000
export CLAIM_CAPACITY=100Mi
export CONTROLLER_NAMESPACE=fn-controller

export COMPOSE_FILE="docker-compose-integration-tests.yaml"

echo "Starting docker compose"
docker compose -f "$COMPOSE_FILE" run --quiet-pull --name keycloak-test-initializer kc_init
exit_code=$?
if [[ exit_code -gt 0 ]]; then
    echo "Something went wrong. Here are some logs"
    docker compose -f "$COMPOSE_FILE" logs keycloak
    docker compose -f "$COMPOSE_FILE" logs kc_init
fi
echo "Cleaning up compose resources"
docker compose -f "$COMPOSE_FILE" stop
docker compose -f "$COMPOSE_FILE" rm -f
exit $exit_code
