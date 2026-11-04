#!/bin/bash
# Run 2 against the SAME Keycloak, with no restart in between.
#
# THE critical test. Pre-fix this logged "Skipping" and did nothing, because the bootstrap user had
# been deleted by run 1 -- which is why realm config could only ever be applied by restarting
# Keycloak, and why removing the forced restart without this change would freeze realm config.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

echo "=== Run 2: same Keycloak, no restart (service-account path) ==="
run2="$(run_kc_init)"
record_run run2 "$run2"

echo "$run2" | grep -q "Skipping" \
  && fail "second run skipped -- the tmpadmin gate is still in effect" \
  || pass "second run did NOT skip"
echo "$run2" | grep -qE "Logging in as 'fn-service'.*" && echo "$run2" | grep -q "Done!" \
  && pass "second run authenticated as fn-service and completed" \
  || fail "second run did not authenticate as the service account"
echo "$run2" | grep -q "falling back to the bootstrap user" \
  && fail "second run still needed the bootstrap user" \
  || pass "second run needed no bootstrap user (so no Keycloak restart required)"

finish
