#!/bin/bash
# Tests the Gitea client against a real Gitea in Docker (own compose project, removed at exit).
# Usage: ./run_gitea_tests.sh [pytest args]   (default: tests/test_gitea_client.py)

pytest_args="${*:-tests/test_gitea_client.py}"

export PGHOST=db PGDATABASE=gitea_mirror_test PGPORT=5432 PGUSER=admin PGPASSWORD=gitea_mirror_test
export GITEA_MIRROR_DB_USER=$PGUSER GITEA_MIRROR_DB_PASSWORD=$PGPASSWORD
export GITEA_MIRROR_DB_NAME=$PGDATABASE GITEA_MIRROR_DB_HOST=$PGHOST GITEA_MIRROR_DB_PORT=$PGPORT
export PYTHONPATH=/app
export GITEA_MIRROR_GITEA_URL=http://gitea:3000

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-gm-gitea-test-$(uuidgen | cut -c1-8)}"
container="${COMPOSE_PROJECT_NAME}-app"
compose=(docker compose -f docker-compose-tests-ci.yaml -f docker-compose-tests.yaml -f docker-compose-gitea-tests.yaml)

cleanup() {
    echo "Cleaning up compose resources"
    docker rm -f "$container" > /dev/null 2>&1 || true
    "${compose[@]}" down --volumes
}
trap cleanup EXIT

echo "Starting db and gitea (project $COMPOSE_PROJECT_NAME)"
"${compose[@]}" up -d --wait --quiet-pull db gitea || exit 1

echo "Creating the Gitea admin user and token"
"${compose[@]}" exec -T -u git gitea gitea admin user create --admin --username testadmin \
    --password 'Test-pass-1234' --email testadmin@example.com --must-change-password=false > /dev/null || exit 1
GITEA_MIRROR_GITEA_TOKEN=$("${compose[@]}" exec -T -u git gitea gitea admin user generate-access-token \
    --username testadmin --scopes all --raw) || exit 1
export GITEA_MIRROR_GITEA_TOKEN

"${compose[@]}" run --build --name "$container" --entrypoint pytest app -x -v $pytest_args
