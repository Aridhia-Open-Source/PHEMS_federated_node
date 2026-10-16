#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Idempotently create the Gitea repo, webserver Project, and TriggerRepository
# that the other trigger-simulation scripts (init_pr.sh, merge_pr.sh) build on: the
# project, the global secret and trigger repository, and the project's assignment of it.
###############################################################################

source .dev.env
source scripts/gitea.sh

keycloak_secret() {
  kubectl get secret kc-secrets -n "${KEYCLOAK_NAMESPACE:-keycloak}" \
    -o jsonpath="{.data.$1}" | base64 -d
}

KEYCLOAK_SERVICE_PASSWORD="${KEYCLOAK_SERVICE_PASSWORD:-$(keycloak_secret KEYCLOAK_SERVICE_PASSWORD)}"

# Colors for output (gitea.sh's are local to that file's scope once sourced,
# but re-declare here for clarity/independence)
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== 1/3 Gitea repo ===${NC}"
if repo_exists "$TEST_TRIGGER_REPO"; then
  echo "Repo already exists: $GITEA_URL/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO"
else
  token=$(get_token "$GITEA_ADMIN_USER")
  curl -sf -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/user/repos" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$TEST_TRIGGER_REPO\",\"description\":\"Trigger-repository simulation\",\"private\":false,\"auto_init\":true}" | jq -r '.clone_url'
fi

default_branch=$(curl -sf -H "Authorization: token $(get_token "$GITEA_ADMIN_USER")" \
  "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO" | jq -r '.default_branch')
echo "Default branch: $default_branch"

echo -e "${BLUE}=== 2/3 Webserver project ===${NC}"
BACKEND_TOKEN=$(curl -s "$BACKEND_URL/login" \
  --fail-with-body \
  --header "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=${KEYCLOAK_SERVICE_USER}" \
  --data-urlencode "password=${KEYCLOAK_SERVICE_PASSWORD}" | jq -r -e '.token')

project_id=$(curl -s "$BACKEND_URL/projects" \
  --header "Content-Type: application/json" \
  --header "Authorization: Bearer $BACKEND_TOKEN" \
  --data "{\"name\": \"$TEST_PROJECT_NAME\", \"description\": \"Trigger-repository simulation\"}" | jq -r '.id // empty')

if [ -z "$project_id" ]; then
  echo "Project already exists, looking up id..."
  project_id=$(curl -sf "$BACKEND_URL/projects" \
    --header "Authorization: Bearer $BACKEND_TOKEN" | jq -r --arg name "$TEST_PROJECT_NAME" '.items[] | select(.name == $name) | .id')
fi
echo "Project id: $project_id"

echo -e "${BLUE}=== 3/3 Secret, global trigger repository, project link ===${NC}"
# The secret and the repository are global; the project holds a link to the repository.
# The secret holds a placeholder token until `fncli init-git-secret` writes a real one.
secret_label="$TEST_TRIGGER_REPO-creds"
if ! curl -sf "$BACKEND_URL/global/secrets/$secret_label" \
  --header "Authorization: Bearer $BACKEND_TOKEN" > /dev/null; then
  curl -sf "$BACKEND_URL/global/secrets" \
    --header "Content-Type: application/json" \
    --header "Authorization: Bearer $BACKEND_TOKEN" \
    --data "{\"label\": \"$secret_label\", \"provider\": \"K8S\", \"values\": {\"TOKEN\": \"unset\"}}" > /dev/null
fi
echo "Secret: $secret_label"

repo_id=$(curl -sf "$BACKEND_URL/global/repositories/triggers" \
  --header "Authorization: Bearer $BACKEND_TOKEN" | jq -r --arg path "$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO" '.[] | select(.uri | endswith($path)) | .id')
if [ -z "$repo_id" ]; then
  repo_id=$(curl -sf "$BACKEND_URL/global/repositories/triggers" \
    --header "Content-Type: application/json" \
    --header "Authorization: Bearer $BACKEND_TOKEN" \
    --data "{\"uri\": \"$TEST_TRIGGER_REPO_URI\", \"provider\": \"gitea\", \"api_uri\": \"$GITEA_API_URI\", \"secret_label\": \"$secret_label\"}" | jq -r '.id')
fi
echo "Trigger repository id: $repo_id"

if ! curl -sf "$BACKEND_URL/projects/$project_id/repositories/triggers/$repo_id" \
  --header "Authorization: Bearer $BACKEND_TOKEN" > /dev/null; then
  curl -sf -X PUT "$BACKEND_URL/projects/$project_id/repositories/triggers/$repo_id" \
    --header "Content-Type: application/json" \
    --header "Authorization: Bearer $BACKEND_TOKEN" \
    --data "{\"watch_dir\": \"$TEST_TRIGGER_REPO_WATCH_DIR\", \"base_branch\": \"$default_branch\"}" > /dev/null
fi
echo "Linked to project $project_id"

echo
echo -e "${BLUE}=== Fresh GET: project ===${NC}"
curl -sf "$BACKEND_URL/projects/$project_id" \
  --header "Authorization: Bearer $BACKEND_TOKEN" | jq .

echo
echo -e "${BLUE}=== Fresh GET: trigger repository link ===${NC}"
curl -sf "$BACKEND_URL/projects/$project_id/repositories/triggers/$repo_id" \
  --header "Authorization: Bearer $BACKEND_TOKEN" | jq .

echo
echo -e "${GREEN}=== init_repo complete ===${NC}"
echo "Project: $TEST_PROJECT_NAME (id $project_id)"
echo "Trigger repository: $TEST_TRIGGER_REPO_URI (id $repo_id, watch_dir $TEST_TRIGGER_REPO_WATCH_DIR)"
echo "Gitea repo page: $GITEA_URL/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO"
