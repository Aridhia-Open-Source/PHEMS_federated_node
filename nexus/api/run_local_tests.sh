#!/bin/bash
# Fast local runs: pytest in a venv against a postgres container, one database per caller so parallel
# runs don't collide. CI-style runs (docker compose) are run_tests.sh.
#   NEXUS_TEST_DB=nexus_tasks ./run_local_tests.sh tests/test_task_launch.py
# Runs on pytest-xdist workers, each with its own database (conftest.py); NEXUS_TEST_WORKERS=0 runs serially.
# Needs: the venv at $NEXUS_VENV (default /tmp/nexus-venv) and
#   docker run -d --name nexus-test-db -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=test_app -p 55432:5432 postgres:17-alpine
set -euo pipefail
cd "$(dirname "$0")"
db="${NEXUS_TEST_DB:-test_app}"
docker exec nexus-test-db psql -U admin -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
    || docker exec nexus-test-db createdb -U admin "$db"
export DATABASE_HOST=localhost DATABASE_PORT=55432 DATABASE_USER=admin DATABASE_PASSWORD=test_app DATABASE_NAME="$db"
export SERVICES_KEYCLOAK_URL=http://keycloak:8080 SERVICES_KEYCLOAK_REALM=FederatedNode
export SERVICES_KEYCLOAK_CLIENT=global SERVICES_KEYCLOAK_ADMIN=admin
export SERVICES_KEYCLOAK_SERVICE_USER=fn-service SERVICES_KEYCLOAK_SERVICE_PASSWORD=servicepass1
export SERVICES_KEYCLOAK_SECRET=qwtirtvJJ4PW4skOlW6Oifk2 SERVICES_DAGSTER_URI=http://dagster:3000
export NAMESPACES_SECRETS=default NAMESPACES_TASKS=tasks NODE_HOSTNAME=localhost:5000 PYTHONPATH="$PWD"
export TASKS_LIMITS_MAX_CPU=4 TASKS_LIMITS_MAX_MEMORY=16Gi
export TASKS_LIMITS_DEFAULT_LIMIT_CPU=2 TASKS_LIMITS_DEFAULT_LIMIT_MEMORY=4Gi
exec timeout 600 "${NEXUS_VENV:-/tmp/nexus-venv}/bin/pytest" -p no:cacheprovider --no-cov -q -n "${NEXUS_TEST_WORKERS:-auto}" "$@"
