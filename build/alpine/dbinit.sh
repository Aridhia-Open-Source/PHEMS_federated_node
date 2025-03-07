#!/bin/sh

psql -d postgres -U "$PGUSER" -tc "SELECT 1 FROM pg_database WHERE datname = '$NEW_DB'" | \
    grep -q 1 || psql -d postgres -U "$PGUSER" -c "CREATE DATABASE \"$NEW_DB\""
