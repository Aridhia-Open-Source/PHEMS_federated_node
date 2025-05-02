#!/bin/sh

set -e

echo "DB info:"
echo "Host: ${PGHOST}"
echo "User: ${PGUSER}"
echo "DB: fn_${PGDATABASE}"

psql -d "fn_${PGDATABASE}" -h "${PGHOST}" -U "${PGUSER}" -f - <<SQL
    DELETE FROM credential WHERE user_id IN (SELECT user_id FROM user_entity WHERE username = 'admin');
    DELETE FROM user_role_mapping WHERE user_id IN (SELECT user_id FROM user_entity WHERE username = 'admin');
    DELETE FROM user_entity WHERE username = 'admin';
SQL
kubectl delete pods -n "${KC_NAMESPACE}" -l app=keycloak
