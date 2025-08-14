#!/bin/sh

set -e

echo "DB info:"
echo "Host: ${PGHOST}"
echo "User: ${PGUSER}"
echo "DB: ${PGDATABASE}"

psql -d "${PGDATABASE}" -h "${PGHOST}" -U "${PGUSER}" -f - <<SQL
    DELETE FROM credential WHERE user_id IN (SELECT id FROM user_entity WHERE username = 'admin');
    DELETE FROM user_role_mapping WHERE user_id IN (SELECT id FROM user_entity WHERE username = 'admin');
    DELETE FROM user_entity WHERE username = 'admin';
SQL
