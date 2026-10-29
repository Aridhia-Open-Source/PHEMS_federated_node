#!/bin/bash
# Run 1: first install against a fresh database -- the single-run case, which is all the previous
# integration script covered.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

echo "=== Run 1: first install (bootstrap path) ==="
run1="$(run_kc_init)"
record_run run1 "$run1"

echo "$run1" | grep -q "Done!" && pass "first run completes" || fail "first run did not complete"
echo "$run1" | grep -q "falling back to the bootstrap user" \
  && pass "first run uses the bootstrap user (fn-service does not exist yet)" \
  || fail "first run did not use the bootstrap path"

finish
