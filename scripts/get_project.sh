#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Show the Project and TriggerRepository DB objects (as the backend API
# currently sees them) for the trigger-repository simulation set up by
# init_repo.sh.
###############################################################################

source .dev.env
source scripts/gitea.sh

KEYCLOAK_SERVICE_PASSWORD="${KEYCLOAK_SERVICE_PASSWORD:-$(kubectl get secret kc-secrets -n "${KEYCLOAK_NAMESPACE:-keycloak}" -o jsonpath='{.data.KEYCLOAK_SERVICE_PASSWORD}' | base64 -d)}"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

BACKEND_TOKEN=$(curl -s "$BACKEND_URL/login" \
  --fail-with-body \
  --header "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=${KEYCLOAK_SERVICE_USER}" \
  --data-urlencode "password=${KEYCLOAK_SERVICE_PASSWORD}" | jq -r -e '.token')

echo -e "${BLUE}=== Project: $TEST_PROJECT_NAME ===${NC}"
project=$(curl -sf "$BACKEND_URL/projects" \
  --header "Authorization: Bearer $BACKEND_TOKEN" \
  | jq --arg name "$TEST_PROJECT_NAME" '.items[] | select(.name == $name)')

if [ -z "$project" ]; then
  echo "Not found. Run init_repo.sh first."
else
  echo "$project" | jq .
  project_id=$(echo "$project" | jq -r '.id')
fi

echo
echo -e "${BLUE}=== Trigger repository: $GITEA_ADMIN_USER/$TEST_TRIGGER_REPO ===${NC}"
repo=$(curl -sf "$BACKEND_URL/trigger_repositories" \
  --header "Authorization: Bearer $BACKEND_TOKEN" \
  | jq --arg path "$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO" '.[] | select(.path == $path)')

if [ -z "$repo" ]; then
  echo "Not found. Run init_repo.sh first."
else
  echo "$repo" | jq .
fi

echo
echo -e "${GREEN}=== get_project complete ===${NC}"
