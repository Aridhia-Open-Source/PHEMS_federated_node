#!/bin/sh

DB_EXISTS=$(psql -d postgres -U "$PGUSER" -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")

if [ "$DB_EXISTS" != "1" ]; then
    echo "Creating $DB_NAME database..."
    psql -d postgres -U "$PGUSER" -c "CREATE DATABASE \"$DB_NAME\""
    echo "Database $DB_NAME created"
else
    echo "Database $DB_NAME already exists"
fi
