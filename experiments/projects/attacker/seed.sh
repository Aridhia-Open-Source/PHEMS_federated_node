#!/usr/bin/env bash
# Prints the SQL that seeds the attacker's database: the two schemas the task contract names
# and one table. It drops and recreates its own schemas, so it is safe to re-run.
set -euo pipefail
cat <<'SQL'
DROP SCHEMA IF EXISTS cdm CASCADE;
DROP SCHEMA IF EXISTS results CASCADE;
CREATE SCHEMA cdm;
CREATE SCHEMA results;
CREATE TABLE cdm.person (person_id integer PRIMARY KEY);
INSERT INTO cdm.person VALUES (1), (2), (3);
SQL
