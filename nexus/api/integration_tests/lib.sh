#!/bin/bash
# Sourced by every shell step. The orchestrator exports COMPOSE_FILE, ARTIFACTS, KC_IP and the
# Keycloak env; a step only needs the helpers below.
#
# A step counts its own failures and exits with that count. The orchestrator sums the exit codes, so
# a step must always end by calling finish.

COMPOSE="docker compose -f $COMPOSE_FILE"

_failures=0
pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1"; _failures=$((_failures + 1)); }
finish() { exit $_failures; }

run_kc_init() {
  # --rm and no fixed --name, so repeat runs cannot collide on a leftover container.
  $COMPOSE run --rm --no-deps -T kc_init 2>&1
}

# kc-init's own output is the evidence for most assertions, so it is echoed indented rather than
# swallowed, and kept on disk for the later steps that assert across runs.
record_run() {
  local name="$1" output="$2"
  printf '%s' "$output" > "$ARTIFACTS/$name.log"
  printf '%s' "$output" | grep -E "^(INFO|ERROR)" | sed 's/^/    /'
}

run_log() { cat "$ARTIFACTS/$1.log"; }
