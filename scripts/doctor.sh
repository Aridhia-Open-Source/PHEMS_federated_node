#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Doctor - checks the dev environment `mise run setup` builds: mise itself, the
# three virtualenvs (root, nexus/api, dagster) and where fncli resolves.
# One line per check, marked ✓ or ✗ (never colour alone). Prints every check,
# then exits 1 if any failed.
# Usage: doctor.sh   (or mise run doctor)
###############################################################################

cd "$(dirname "$0")/.."
failed=0

ok() { echo "✓ $*"; }
bad() { echo "✗ $*"; failed=1; }

if out=$(mise doctor 2>&1); then
  ok "mise doctor: no problems"
else
  bad "mise doctor reported problems:"
  echo "$out"
fi

for venv in .venv nexus/api/.venv dagster/.venv; do
  dir=$(dirname "$venv")
  if [ ! -x "$venv/bin/python" ]; then
    bad "$venv: missing, run mise run setup"
    continue
  fi
  version=$(mise -C "$dir" exec -- python --version)
  if out=$(mise -C "$dir" exec -- python -m pip check 2>&1); then
    ok "$venv: $version, pip check clean"
  else
    bad "$venv: $version, pip check failed:"
    echo "$out"
  fi
done

# `command` is a shell builtin, so it needs sh to run it
fncli=$(mise exec -- sh -c 'command -v fncli' || true)
# relative when inside the repo, full path otherwise
shown=${fncli#"$PWD"/}
if [ "$shown" = ".venv/bin/fncli" ]; then
  ok "fncli: $shown"
else
  bad "fncli: ${shown:-not found}, expected .venv/bin/fncli"
fi

exit "$failed"
