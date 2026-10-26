#!/usr/bin/env bash
# End-to-end check of the shared-resources flow against a real dev cluster: global resources and project resources created
# with fncli, Gitea PRs ingested by Dagster, tasks created and run.
#
#   scripts/e2e_shared_resources.sh            run it, tear the project down at the end
#   KEEP=1 scripts/e2e_shared_resources.sh    leave the project in place to look at
#   SKIP_TASKS=1 scripts/e2e_shared_resources.sh   stop after the PRs are evaluated and tasks exist (no run needed)
#
# Needs (see dagster/fncli/README.md and EXAMPLES.md): kubectl on context kind-fn, `make deploy` done, `tilt up` green
# with the port-forwards running (backend :5000, Gitea :4000, Dagster :3000), fncli installed with pipx, .dev.env present.
#
# The webserver pytest suite is not run by this script.
set -uo pipefail

cd "$(dirname "$0")/.."

PIPX_VENVS="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || echo "$HOME/.local/share/pipx/venvs")"
PY="$PIPX_VENVS/phems/bin/python"
CHECK="$PY scripts/e2e_check.py"
step() { printf '\n=== %s\n' "$*"; }
fail() { printf '\nFAILED at: %s\n' "$*"; failed=1; }

failed=0

step "Preflight"
[[ "$(kubectl config current-context)" == "kind-fn" ]] || { echo "kubectl context must be kind-fn"; exit 2; }
[[ -x "$PY" ]] || { echo "fncli not found in pipx: pipx install --force --editable './dagster[cli]'"; exit 2; }
fncli hello-world >/dev/null || { echo "fncli does not run"; exit 2; }
curl -fsS -o /dev/null localhost:5000/ready 2>/dev/null || curl -sS -o /dev/null localhost:5000 || { echo "backend not on :5000 (tilt port-forwards?)"; exit 2; }
curl -sS -o /dev/null localhost:4000 || { echo "Gitea not on :4000"; exit 2; }
curl -sS -o /dev/null localhost:3000 || { echo "Dagster not on :3000"; exit 2; }

cleanup() {
  if [[ "${KEEP:-0}" == "1" ]]; then
    echo; echo "KEEP=1: leaving the project and sensors in place. Clean up with: fncli stop-sensor --group all; fncli teardown-project -y"
    return
  fi
  step "Teardown"
  fncli stop-sensor --group all || true
  fncli teardown-project -y || echo "teardown reported problems (check by hand)"
}
trap cleanup EXIT

step "1. setup-project (global secrets, repos, dataset, project and its resources, healthcheck)"
fncli setup-project || { fail "setup-project"; exit 1; }
fncli project-healthcheck || fail "project-healthcheck is not ok"

step "2. start sensors (run-status sensors first, then the rest)"
fncli start-sensor --group all || { fail "start-sensor"; exit 1; }

step "3. open and merge three PRs: watched, unwatched, invalid"
fncli open-pr --kind watched --merge || fail "open-pr watched"
fncli open-pr --kind unwatched --merge || fail "open-pr unwatched"
fncli open-pr --kind invalid --merge || fail "open-pr invalid"

step "4. wait for ingest and evaluate: expect YIELDED (with a task) and REJECTED, and no trigger for the unwatched PR"
$CHECK wait-prs --timeout 300 || { fail "PRs not evaluated"; fncli sensor-status; }

if [[ "${SKIP_TASKS:-0}" != "1" ]]; then
  step "5. wait for the task to run to SUCCESS (needs the launcher, run-status sensors and a working task image)"
  $CHECK wait-tasks --timeout 600 || { fail "task did not reach SUCCESS"; fncli sensor-status; }
else
  step "5. skipped (SKIP_TASKS=1)"
fi

step "6. final snapshot"
$CHECK snapshot || true

if [[ $failed -eq 0 ]]; then
  printf '\nE2E OK\n'
else
  printf '\nE2E FAILED (see FAILED lines above)\n'
  exit 1
fi
