#!/bin/bash
# Asserts across the two runs recorded by steps 01 and 02, so it cannot run standalone.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

echo "=== Migrations are run-once ==="
run1="$(run_log run1)"
run2="$(run_log run2)"

echo "$run1" | grep -q "Applying realm migration 1" \
  && pass "run 1 applied migrations" || fail "run 1 applied no migrations"
echo "$run2" | grep -q "Applying realm migration" \
  && fail "run 2 re-applied a migration (not run-once)" \
  || pass "run 2 re-applied nothing"
echo "$run2" | grep -q "Realm is up to date" \
  && pass "run 2 reports the realm up to date" || fail "run 2 did not report up-to-date"

finish
