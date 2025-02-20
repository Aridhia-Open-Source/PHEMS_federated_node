#!/bin/sh

set -e

TOKEN=$(curl \
  "${BACKEND_URL}/login" \
  --fail-with-body \
  --header "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=${KEYCLOAK_ADMIN}" \
  --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}" | jq -r -e '.token'
)

echo "### Test Fetch Dataset list ###"
curl "${BACKEND_URL}/datasets" \
    --fail-with-body \
    --header "Authorization: Bearer ${TOKEN}" | jq -e

echo "### Test Fetch Containers list ###"
curl "${BACKEND_URL}/containers" \
    --fail-with-body \
    --header "Authorization: Bearer ${TOKEN}" | jq -e

echo "### Test Create User ###"
USER_TEMP=$(curl "${BACKEND_URL}/users" \
    --fail-with-body \
    --header "Content-Type: application/json" \
    --header "Authorization: Bearer ${TOKEN}" \
    --data-raw "{
        \"email\": \"testuser@phems.com\",
        \"role\": \"Users\"
    }"| jq -r -e '.tempPassword')

NEW_PASS="{{ randAlphaNum 24 }}"
echo "Resetting pass"
curl -s --request PUT "${BACKEND_URL}/users/reset-password" \
    --fail-with-body \
    --header "Content-Type: application/json" \
    --data-raw "{
        \"email\": \"testuser@phems.com\",
        \"tempPassword\": \"${USER_TEMP}\",
        \"newPassword\": \"${NEW_PASS}\"
    }"

echo "Login new creds"
curl "${BACKEND_URL}/login" \
    --fail-with-body \
    --header "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=testuser@phems.com" \
    --data-urlencode "password=${NEW_PASS}"
