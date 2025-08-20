#!/bin/bash

ADMIN_REFRESH_TOKEN=$(curl "${KEYCLOAK_URL}/realms/FederatedNode/protocol/openid-connect/token" \
    --silent \
    --header "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "username=${KEYCLOAK_ADMIN}" \
    --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}" \
    --data-urlencode "client_id=admin-cli" | jq -r '.access_token')
# On keycloak 24+, the pass encryption is heavier, so we set it
# to the lower lever as in 23. It's only for the unittests
curl --request PUT \
  --url "${KEYCLOAK_URL}/admin/realms/FederatedNode" \
  --header "Authorization: Bearer $ADMIN_REFRESH_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"passwordPolicy": "hashAlgorithm(pbkdf2-sha256) and hashIterations(27500)"}'

pytest -v .
