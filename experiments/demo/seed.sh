#!/usr/bin/env bash
# Prints the SQL that seeds the demo database: a cdm schema with one tiny table and an empty
# results schema. It drops and recreates its own schemas, so it is safe to re-run.
set -euo pipefail
cat <<'SQL'
DROP SCHEMA IF EXISTS cdm CASCADE;
DROP SCHEMA IF EXISTS results CASCADE;
CREATE SCHEMA cdm;
CREATE SCHEMA results;
CREATE TABLE cdm.person (person_id integer PRIMARY KEY, year_of_birth integer);
INSERT INTO cdm.person VALUES (1, 1970), (2, 1985), (3, 2001);
GRANT USAGE ON SCHEMA cdm TO demo_user;
GRANT SELECT ON ALL TABLES IN SCHEMA cdm TO demo_user;
GRANT USAGE, CREATE ON SCHEMA results TO demo_user;
SQL
