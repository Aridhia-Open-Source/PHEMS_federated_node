#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Backend Login Test - confirms the webserver can authenticate a service user
# via Keycloak (POST /login), independent of any other trigger-repo setup.
###############################################################################

source .dev.env

BACKEND_URL="${BACKEND_URL:-http://localhost:5000}"
KEYCLOAK_SERVICE_PASSWORD="${KEYCLOAK_SERVICE_PASSWORD:-$(kubectl get secret kc-secrets -n "${KEYCLOAK_NAMESPACE:-keycloak}" -o jsonpath='{.data.KEYCLOAK_SERVICE_PASSWORD}' | base64 -d)}"

echo "Logging in to $BACKEND_URL as $KEYCLOAK_SERVICE_USER..."

TOKEN=$(curl -s "$BACKEND_URL/login" \
  --fail-with-body \
  --header "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=${KEYCLOAK_SERVICE_USER}" \
  --data-urlencode "password=${KEYCLOAK_SERVICE_PASSWORD}" | jq -r -e '.token')

echo "Login OK"
echo "Token: $TOKEN"
