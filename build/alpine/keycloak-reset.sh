#!/bin/sh

set -e

echo "DB info:"
echo "Host: ${KC_DB_URL_HOST}"
echo "User: ${KC_DB_USERNAME}"
echo "DB: ${PGDATABASE}"

resetCreds()
{
psql -d "${PGDATABASE}" -h "${KC_DB_URL_HOST}" -U "${KC_DB_USERNAME}" -f - <<SQL
    UPDATE client SET secret='${KEYCLOAK_SECRET}' WHERE client_id = 'global';
    DELETE FROM credential WHERE user_id IN (SELECT id FROM user_entity WHERE username = '$1');
    DELETE FROM user_role_mapping WHERE user_id IN (SELECT id FROM user_entity WHERE username = '$1');
    DELETE FROM user_attribute WHERE user_id IN (SELECT id FROM user_entity WHERE username = '$1');
    DELETE FROM user_entity WHERE username = '$1';
SQL
}

resetCreds "admin"
resetCreds "$KC_BOOTSTRAP_ADMIN_USERNAME"
