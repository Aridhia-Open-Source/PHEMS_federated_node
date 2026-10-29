#!/bin/bash
# The requirement: an admin can reconfigure Keycloak (e.g. add an external IdP) and the platform must
# not revert it. partialImport uses ifResourceExists=SKIP precisely so this holds.
set -uo pipefail
HERE="$(dirname "$0")"
. "$HERE/lib.sh"

echo "=== Operator configuration survives a kc-init run ==="
PYTHONPATH="$HERE" python3 "$HERE/_seed_operator_config.py" || fail "could not seed operator config"

run3="$(run_kc_init)"
record_run run3 "$run3"
echo "$run3" | grep -q "Done!" \
  && pass "run 3 completes with operator config present" || fail "run 3 failed"

PYTHONPATH="$HERE" python3 "$HERE/_verify_operator_config.py" || _failures=$((_failures + 1))

finish
