#!/bin/bash
# Fast local runs: pytest in a venv against a postgres container, one database per caller so parallel
# runs don't collide. CI-style runs (docker compose) are run_tests.sh.
#   NEXUS_TEST_DB=nexus_tasks ./run_local_tests.sh tests/test_task_launch.py
# Needs: the venv at $NEXUS_VENV (default /tmp/nexus-venv) and
#   docker run -d --name nexus-test-db -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=test_app -p 55432:5432 postgres:17-alpine
set -euo pipefail
cd "$(dirname "$0")"
db="${NEXUS_TEST_DB:-test_app}"
docker exec nexus-test-db psql -U admin -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
    || docker exec nexus-test-db createdb -U admin "$db"
export PGHOST=localhost PGPORT=55432 NEXUS_DB_USER=admin NEXUS_DB_PASSWORD=test_app NEXUS_DB_NAME="$db"
export KEYCLOAK_URL=http://keycloak:8080 KEYCLOAK_REALM=FederatedNode KEYCLOAK_CLIENT=global KEYCLOAK_ADMIN=admin
export KEYCLOAK_ADMIN_PASSWORD=password1 KEYCLOAK_SERVICE_USER=fn-service KEYCLOAK_SERVICE_PASSWORD=servicepass1
export KEYCLOAK_SECRET=qwtirtvJJ4PW4skOlW6Oifk2 SECRETS_NAMESPACE=default TASK_NAMESPACE=tasks
export KEYCLOAK_NAMESPACE=keycloak PUBLIC_URL=localhost:5000 PYTHONPATH="$PWD"
exec timeout 600 "${NEXUS_VENV:-/tmp/nexus-venv}/bin/pytest" -p no:cacheprovider --no-cov -q "$@"
