#!/bin/sh

set -e

TEST_USER_EMAIL="testuser${HASH_RAND}@phems.com"
TEST_USER_EMAIL_URL_SAFE=$(printf "%s" "${TEST_USER_EMAIL}" | jq -sRr @uri)
TEST_DB_NAME="testing${HASH_RAND}"
echo "Dataset Test: ${TEST_DB_NAME}"
echo "Test User email: ${TEST_USER_EMAIL}"

TOKEN=$(curl --silent \
  "${BACKEND_URL}/login" \
  --fail-with-body \
  --header "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=${KEYCLOAK_ADMIN}" \
  --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}" | jq -r -e '.token'
)

test_dataset_list(){
    printf "[test]\t### Test Fetch Dataset list ###\n\n"
    curl --silent "${BACKEND_URL}/datasets" \
        --fail-with-body \
        --header "Authorization: Bearer ${TOKEN}" > /dev/null 2>&1
}

test_containers_list() {
    printf "[test]\t### Test Fetch Containers list ###\n\n"
    curl --silent "${BACKEND_URL}/containers" \
        --fail-with-body \
        --header "Authorization: Bearer ${TOKEN}" > /dev/null 2>&1
}

test_create_user() {
    printf "[test]\t### Test Create User ###\n\n"
    USER_TEMP=$(curl --silent "${BACKEND_URL}/users" \
        --fail-with-body \
        --header "Content-Type: application/json" \
        --header "Authorization: Bearer ${TOKEN}" \
        --data-raw "{
            \"email\": \"${TEST_USER_EMAIL}\",
            \"role\": \"Users\"
        }"| jq -r -e '.tempPassword')

    printf "[test]\t\tResetting pass\n"
    curl --silent --request PUT "${BACKEND_URL}/users/reset-password" \
        --fail-with-body \
        --header "Content-Type: application/json" \
        --data-raw "{
            \"email\": \"${TEST_USER_EMAIL}\",
            \"tempPassword\": \"${USER_TEMP}\",
            \"newPassword\": \"${NEW_PASS}\"
        }" > /dev/null 2>&1

    # If the login is too fast, it will tend to fail
    sleep 1
    printf "[test]\t\tLogin new creds\n"
    curl --silent "${BACKEND_URL}/login" \
        --fail-with-body \
        --header "Content-Type: application/x-www-form-urlencoded" \
        --data-urlencode "username=${TEST_USER_EMAIL}" \
        --data-urlencode "password=${NEW_PASS}" > /dev/null 2>&1
}

test_create_dataset() {
    printf "[test]\t### Test create Dataset ###\n\n"

    DS_ID=$(curl --silent "${BACKEND_URL}/datasets/" \
        --fail-with-body \
        --header "Content-Type: application/json" \
        --header "Authorization: Bearer ${TOKEN}" \
        --data "{
            \"name\": \"${TEST_DB_NAME}\",
            \"host\": \"testdb\",
            \"port\": 5432,
            \"username\": \"user\",
            \"password\": \"password1\",
            \"extra_connection_args\": \";TrustServerCertificate=Yes\"
        }" | jq -e -r '.dataset_id')
}

test_dar() {
    printf "[test]\t### Test DAR process ###\n\n"
    USER_TOKEN=$(curl --silent "${BACKEND_URL}/datasets/token_transfer" \
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
    curl --silent "${BACKEND_URL}/datasets/${TEST_DB_NAME}" \
        --fail-with-body \
        --header "project-name: project" \
        --header "Authorization: Bearer ${USER_TOKEN}" > /dev/null 2>&1
}

exit_code=0

test_dataset_list || printf "[ERROR]\tFailed fetching dataset list test\n"; exit_code=1
test_containers_list || printf "[ERROR]\tFailed fetching containers list test\n"; exit_code=1
test_create_user || printf "[ERROR]\tFailed create user test\n"; exit_code=1
test_create_dataset || printf "[ERROR]\tFailed create a dataset test\n"; exit_code=1
test_dar || printf "[ERROR]\tFailed dar test\n"; exit_code=1

printf "\n[cleanup]\t#### CLEANUP #####\n\n"

TOKEN=$(curl --silent "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/realms/FederatedNode/protocol/openid-connect/token" \
    --header "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "username=${KEYCLOAK_ADMIN}" \
    --data-urlencode "password=${KEYCLOAK_ADMIN_PASSWORD}" \
    --data-urlencode "client_id=admin-cli" | jq -r '.access_token')

printf "[cleanup]\tRemoving test user\n"
USER_ID=$(curl --silent "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/admin/realms/FederatedNode/users?email=${TEST_USER_EMAIL}" \
    --header "Authorization: Bearer ${TOKEN}" | jq -r '.[].id')

if [ -n "$USER_ID" ]; then
    printf "[cleanup]\tFound user %s\n" "${USER_ID}"
    curl --silent --request DELETE "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/admin/realms/FederatedNode/users/${USER_ID}" \
        --header "Authorization: Bearer ${TOKEN}" > /dev/null 2>&1
fi

printf "[cleanup]\tPurging DAR client\n"
CLIENT_ID=$(curl --silent "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/admin/realms/FederatedNode/clients?clientId=${TEST_USER_EMAIL_URL_SAFE}&search=true" \
    --header "Authorization: Bearer ${TOKEN}" | jq -r '.[0].id')

if [ -n "$CLIENT_ID" ]; then
    printf "[cleanup]\tGot client ID: %s\n" "${CLIENT_ID}"
    curl --silent  --request DELETE "http://keycloak.${KEYCLOAK_NAMESPACE}.svc/admin/realms/FederatedNode/clients/${CLIENT_ID}" \
        --header "Authorization: Bearer ${TOKEN}" > /dev/null 2>&1
fi

printf "[cleanup]\tRemoving test db entry\n"
psql -h db -U "$PGUSER" -d "$PGDATABASE" -c "DELETE FROM datasets WHERE name = '${TEST_DB_NAME}';"  > /dev/null 2>&1

if [ $exit_code -gt 0 ]; then
    exit $exit_code
fi

echo "All tests passed successfully!!"
