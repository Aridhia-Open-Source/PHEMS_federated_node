#!/bin/sh

set -e

HASH_RAND=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 4; echo)
NEW_PASS=$(tr -dc 'A-Za-z0-9!#$%&' </dev/urandom | head -c 12; echo)

TEST_USER_EMAIL="testuser${HASH_RAND}@phems.com"
TEST_USER_EMAIL_URL_SAFE=$(printf "%s" "${TEST_USER_EMAIL}" | jq -sRr @uri)
TEST_DB_NAME="testing${HASH_RAND}"
TEST_SECRET_LABEL="testing-${HASH_RAND}"
echo "Dataset Test: ${TEST_DB_NAME}"
echo "Test User email: ${TEST_USER_EMAIL}"

TOKEN=$(curl "${NEXUS_API_URL}/login" \
    --silent \
    --fail-with-body \
    --header "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=${KEYCLOAK_SERVICE_USER}" \
    --data-urlencode "password=${KEYCLOAK_SERVICE_PASSWORD}" | jq -r -e '.token'
)

test_dataset_list(){
    printf "[test]\t### Test Fetch Dataset list ###\n\n"
    curl "${NEXUS_API_URL}/global/datasets" \
        --silent \
        --fail-with-body \
        --header "Authorization: Bearer ${TOKEN}" > /dev/null 2>&1
}

test_create_user() {
    printf "[test]\t### Test Create User ###\n\n"
    USER_TEMP=$(curl "${NEXUS_API_URL}/global/users" \
        --silent \
        --fail-with-body \
        --header "Content-Type: application/json" \
        --header "Authorization: Bearer ${TOKEN}" \
        --data-raw "{
            \"email\": \"${TEST_USER_EMAIL}\",
            \"role\": \"Users\"
        }"| jq -r -e '.tempPassword')

    printf "[test]\t\tResetting pass\n"
    curl --request PUT "${NEXUS_API_URL}/global/users/reset-password" \
        --silent \
        --fail-with-body \
        --header "Content-Type: application/json" \
        --data-raw "{
            \"email\": \"${TEST_USER_EMAIL}\",
            \"tempPassword\": \"${USER_TEMP}\",
            \"newPassword\": \"${NEW_PASS}\"
        }" > /dev/null 2>&1

    # If the login is too fast, it will tend to fail
    sleep .5
    printf "[test]\t\tLogin new creds\n"
    curl "${NEXUS_API_URL}/login" \
        --silent \
        --fail-with-body \
        --header "Content-Type: application/x-www-form-urlencoded" \
        --data-urlencode "username=${TEST_USER_EMAIL}" \
        --data-urlencode "password=${NEW_PASS}" > /dev/null 2>&1
}

test_create_dataset() {
    printf "[test]\t### Test create Dataset ###\n\n"

    curl "${NEXUS_API_URL}/global/secrets" \
        --silent \
        --fail-with-body \
        --header "Content-Type: application/json" \
        --header "Authorization: Bearer ${TOKEN}" \
        --data "{
            \"label\": \"${TEST_SECRET_LABEL}\",
            \"provider\": \"K8S\",
            \"values\": {\"USERNAME\": \"user\", \"PASSWORD\": \"password1\"}
        }" > /dev/null 2>&1

    DS_ID=$(curl "${NEXUS_API_URL}/global/datasets/" \
        --silent \
        --fail-with-body \
        --header "Content-Type: application/json" \
        --header "Authorization: Bearer ${TOKEN}" \
        --data "{
            \"name\": \"${TEST_DB_NAME}\",
            \"host\": \"testdb\",
            \"port\": 5432,
            \"secret_label\": \"${TEST_SECRET_LABEL}\",
            \"extra_connection_args\": \";TrustServerCertificate=Yes\"
        }" | jq -e -r '.id')
}

test_dar() {
    # TODO(DAR): POST /datasets/token_transfer was removed, DAR is disconnected for now
    printf "[test]\t### Test DAR process ###\n\n"
    USER_TOKEN=$(curl "${NEXUS_API_URL}/datasets/token_transfer" \
        --silent \
        --fail-with-body \
        --header 'Content-Type: application/json' \
        --header "Authorization: Bearer ${TOKEN}" \
        --data-raw "{
            \"title\": \"Test DAR\",
            \"project_name\": \"project\",
            \"requested_by\": {
                \"email\": \"${TEST_USER_EMAIL}\"
            },
            \"description\": \"testing more projects. A secret one!\",
            \"proj_start\": \"2024-10-01\",
            \"proj_end\": \"2025-12-31\",
            \"dataset_id\": \"${DS_ID}\"
        }" | jq -r -e '.token')

    printf "[test]\t\ttry access dataset info\n"
    curl "${NEXUS_API_URL}/global/datasets/${DS_ID}" \
        --silent \
        --fail-with-body \
        --header "project-name: project" \
        --header "Authorization: Bearer ${USER_TOKEN}" > /dev/null 2>&1
}

exit_code=0

if ! test_dataset_list; then
    printf "[ERROR]\tFailed fetching dataset list test\n"
    exit_code=1
fi
if ! test_create_user; then
    printf "[ERROR]\tFailed create user test\n"
    exit_code=1
fi
if ! test_create_dataset; then
    printf "[ERROR]\tFailed create a dataset test\n"
    exit_code=1
fi
if ! test_dar; then
    printf "[ERROR]\tFailed dar test\n"
    exit_code=1
fi

printf "\n[cleanup]\t#### CLEANUP #####\n\n"

TOKEN=$(curl "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/realms/FederatedNode/protocol/openid-connect/token" \
    --silent \
    --header "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "username=${KEYCLOAK_SERVICE_USER}" \
    --data-urlencode "password=${KEYCLOAK_SERVICE_PASSWORD}" \
    --data-urlencode "client_id=admin-cli" | jq -r '.access_token')

printf "[cleanup]\tRemoving test user\n"
USER_ID=$(curl "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/admin/realms/FederatedNode/users?email=${TEST_USER_EMAIL}" \
    --silent \
    --header "Authorization: Bearer ${TOKEN}" | jq -r '.[0].id')

if [ -n "$USER_ID" ]; then
    printf "[cleanup]\tFound user %s\n" "${USER_ID}"
    curl --request DELETE "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/admin/realms/FederatedNode/users/${USER_ID}" \
        --silent \
        --header "Authorization: Bearer ${TOKEN}" > /dev/null 2>&1
fi

printf "[cleanup]\tPurging DAR client\n"
CLIENT_ID=$(curl "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/admin/realms/FederatedNode/clients?clientId=${TEST_USER_EMAIL_URL_SAFE}&search=true" \
    --silent \
    --header "Authorization: Bearer ${TOKEN}" | jq -r '.[0].id')

if [ -n "$CLIENT_ID" ]; then
    printf "[cleanup]\tGot client ID: %s\n" "${CLIENT_ID}"
    curl  --request DELETE "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/admin/realms/FederatedNode/clients/${CLIENT_ID}" \
        --silent \
        --header "Authorization: Bearer ${TOKEN}" > /dev/null 2>&1
fi

printf "[cleanup]\tRemoving test db entry\n"
# PGHOST/PGPORT/NEXUS_DB_USER/NEXUS_DB_NAME are what nexus-api-configmap publishes.
# This used to hardcode `-h db` and read PGUSER/PGDATABASE, which nothing exports - so
# with `set -e` above, the whole test pod died here before it could report success.
psql -h "$PGHOST" -p "$PGPORT" -U "$NEXUS_DB_USER" -d "$NEXUS_DB_NAME" \
  -c "DELETE FROM datasets WHERE name = '${TEST_DB_NAME}'; DELETE FROM secrets WHERE label = '${TEST_SECRET_LABEL}';" > /dev/null 2>&1

if [ $exit_code -gt 0 ]; then
    exit $exit_code
fi

echo "All tests passed successfully!!"
