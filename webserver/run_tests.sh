#!/bin/bash

echo "Setting up docker-compose env vars"
export PGHOST=db

is_ci=$1

echo "Starting docker compose"
if [[ "$is_ci" != "ci" ]]; then
    docker compose -f docker-compose-tests-ci.yaml -f docker-compose-tests.yaml run --build --name flask-app-test app
    docker cp flask-app-test:/app/artifacts/coverage.xml ../artifacts/
    docker rm flask-app-test
else
    docker compose -f docker-compose-tests-ci.yaml run --build --quiet-pull --name flask-app-test app
    exit_code=$?
    if [[ exit_code -gt 0 ]]; then
        echo "Something went wrong. Here are some logs"
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
