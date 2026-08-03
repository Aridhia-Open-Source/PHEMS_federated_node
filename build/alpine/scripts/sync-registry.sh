#!/bin/sh

set -e

TOKEN=$(curl "${BASE_URL}/login" \
    --fail-with-body \
    --header "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=${KEYCLOAK_SERVICE_USER}" \
    --data-urlencode "password=${KEYCLOAK_SERVICE_PASSWORD}" | jq -r '.token')

curl --request POST "${BASE_URL}/containers/sync" \
    --fail-with-body \
    --header "Content-Type: application/json" \
    --header "Authorization: Bearer ${TOKEN}" | jq
