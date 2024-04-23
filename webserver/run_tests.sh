#!/bin/bash

echo "Setting up docker-compose env vars"
export PGHOST=db
export PGDATABASE=test_app
export PGPORT=5432
export PGUSER=admin
export PGPASSWORD=test_app
export KEYCLOAK_URL=http://keycloak:8080
export KEYCLOAK_REALM=FederatedNode
export KEYCLOAK_SECRET=asdf12ad89123ocasASD129
export KEYCLOAK_CLIENT=global
export KEYCLOAK_ADMIN=admin
export KEYCLOAK_ADMIN_PASSWORD=password1
export PYTHONPATH=/app
export RESULTS_PATH=/tmp/results
export TASK_POD_RESULTS_PATH=/mnt/data
export TASK_NAMESPACE=tasks
export KEYCLOAK_NAMESPACE=keycloak

is_ci=$1

echo "Starting docker compose"
if [[ "$is_ci" != "ci" ]]; then
    docker compose -f docker-compose-tests-ci.yaml -f docker-compose-tests.yaml run --name flask-app-test app
    docker cp flask-app-test:/app/artifacts/coverage.xml ../artifacts/
    docker rm flask-app-test
else
    docker compose -f docker-compose-tests-ci.yaml run --quiet-pull --name flask-app-test app
    exit_code=$?
    if [[ exit_code -gt 0 ]]; then
        echo "Something went wrong. Here are some logs"
        docker compose -f docker-compose-tests-ci.yaml logs keycloak
        docker compose -f docker-compose-tests-ci.yaml logs kc_init
        docker compose -f docker-compose-tests-ci.yaml logs app
    fi
    docker cp flask-app-test:/app/artifacts/coverage.xml ../artifacts/
    echo "Cleaning up compose resources"
    docker compose -f docker-compose-tests-ci.yaml stop
    docker compose -f docker-compose-tests-ci.yaml rm -f
    docker rm flask-app-test
    docker volume rm federated_node_tests_data
    exit $exit_code
fi
