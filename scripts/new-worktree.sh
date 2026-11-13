#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# New worktree - creates a sibling worktree and copies over the gitignored dev
# config (.dev.env, k8s/federated-node/dev.values.yaml, ...) that a fresh
# checkout lacks.
# Usage: new-worktree.sh <name> <branch> [<base-ref>]   (or mise run worktree --name <name> --branch <branch> [--base <ref>])
###############################################################################

NAME="${1:?usage: $0 <name> <branch> [<base-ref>]}"
BRANCH="${2:?usage: $0 <name> <branch> [<base-ref>]}"
BASE="${3:-HEAD}"

# Run from the source checkout, the one this script lives in
cd "$(dirname "$0")/.."
SRC="$PWD"
DEST="../$NAME"

if [ -e "$DEST" ]; then
  echo "$DEST already exists" >&2
  exit 1
fi

echo "=== Creating worktree =========================================================="

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "Branch $BRANCH exists, checking it out (BASE ignored)"
  git worktree add "$DEST" "$BRANCH"
else
  git worktree add -b "$BRANCH" "$DEST" "$BASE"
fi

echo
echo "=== Copying gitignored dev config =============================================="

# Gitignored .env and .yaml files and your triggers/ files, minus vendored, generated and tool directories.
# --update=none never overwrites a file the checkout already has. The greps may match
# nothing on a bare clone, hence || true.
{ git ls-files --others --ignored --exclude-standard | grep -E '\.env$|\.yaml$|^triggers/.*\.json$' || true; } \
  | { grep -vE '(^|/)(\.venv|node_modules|charts|__pycache__|\.claude)/|(^|/)\.tilt' || true; } \
  | while IFS= read -r f; do
      if [ -e "$DEST/$f" ]; then
        echo "kept $f (already there)"
        continue
      fi
      mkdir -p "$DEST/$(dirname "$f")"
      cp --update=none "$SRC/$f" "$DEST/$f"
      echo "copied $f"
    done

echo
echo "=== Next ======================================================================="
echo "cd $DEST && mise run helm-deps && mise run deploy"
