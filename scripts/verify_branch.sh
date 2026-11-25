#!/usr/bin/env bash
# Rebuild the throwaway verify/all branch: dagster-develop + the operator stack top + the flux stack top.
#
#   scripts/verify_branch.sh            # run in a worktree on verify/all with no local changes
#
# The operator top carries the ci, refactor, auth and operator stacks. Known conflicts are resolved by
# rule below (see the table), never by hand, so a rerun is repeatable. Any other conflicted file stops
# the script and names it: that is a cross-stack issue to fix in a stack PR.
# The verify tooling (this script, verify_merge_json.py, verify_resolutions/, verify/) lives only on
# verify/all; it is saved before the reset and committed back on top. Push is left to the caller
# (git push --force-with-lease origin verify/all).
set -euo pipefail

BASE="${VERIFY_BASE:-origin/dagster-develop}"
OPERATOR_TOP="${VERIFY_OPERATOR_TOP:-origin/feat/operator-grants}"
FLUX_TOP="${VERIFY_FLUX_TOP:-origin/feat/flux-remove-copy-secrets}"

cd "$(git rev-parse --show-toplevel)"
[ "$(git branch --show-current)" = "verify/all" ] || { echo "Run this on the verify/all branch" >&2; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "verify/all has local changes" >&2; exit 1; }

SAVE="$(mktemp -d)"
trap 'rm -rf "$SAVE"' EXIT
mkdir -p "$SAVE/scripts"
cp -r scripts/verify_branch.sh scripts/verify_merge_json.py scripts/verify_resolutions "$SAVE/scripts/"
[ -d verify ] && cp -r verify "$SAVE/"
RES="$SAVE/scripts/verify_resolutions"

# How each known conflicted file of the flux merge is resolved:
#   union    both sides only add lines (changelog, index tables)
#   json3    three-way merge by key (a key one side drops stays dropped)
#   theirs   the flux side's delete
#   file     the checked-in resolved file in verify_resolutions/
declare -A RULES=(
  [CHANGELOG.md]=union
  [README.md]=union
  [docs/README.md]=union
  [project/decisions/README.md]=union
  [k8s/federated-node/values.schema.json]=json3
  [k8s/federated-node/templates/copy-secrets.yaml]=theirs
  [k8s/federated-node/tests/upgrades_test.yaml]=file
  [mise.toml]=file
  [scripts/deploy.sh]=file
)
# Resolved files applied even without a conflict (cross-stack fixes; see verify/report.md).
# fixes/*.patch: later bug fixes, applied with git am after the tooling commit.
ALWAYS=(k8s/federated-node/templates/operator-namespace.yaml scripts/deploy.sh)

git fetch -q origin
git reset -q --hard "$BASE"
git merge -q --no-ff --no-edit "$OPERATOR_TOP" -m "merge: operator stack top ($OPERATOR_TOP)"

if ! git merge -q --no-ff --no-edit "$FLUX_TOP" -m "merge: flux stack top ($FLUX_TOP)" >/dev/null 2>&1; then
  unknown=()
  while read -r f; do
    [ -n "${RULES[$f]:-}" ] || unknown+=("$f")
  done < <(git diff --name-only --diff-filter=U)
  if [ ${#unknown[@]} -gt 0 ]; then
    echo "Unknown conflicts, stopping (git merge --abort to undo):" >&2
    printf '  %s\n' "${unknown[@]}" >&2
    exit 1
  fi
  while read -r f; do
    case "${RULES[$f]}" in
      union)
        git show ":1:$f" > "$SAVE/base"; git show ":2:$f" > "$f"; git show ":3:$f" > "$SAVE/theirs"
        git merge-file --union "$f" "$SAVE/base" "$SAVE/theirs"
        git add "$f" ;;
      json3) python3 -I "$SAVE/scripts/verify_merge_json.py" "$f"
             git add "$f" ;;
      theirs) if git cat-file -e ":3:$f" 2>/dev/null; then git checkout --theirs -- "$f"; git add "$f"
              else git rm -q -- "$f"; fi ;;
      file) cp "$RES/$f" "$f"; git add "$f" ;;
    esac
  done < <(git diff --name-only --diff-filter=U)
  git commit -q --no-edit
fi

for f in "${ALWAYS[@]}"; do cp "$RES/$f" "$f"; done
mkdir -p scripts
cp -r "$SAVE/scripts/." scripts/
[ -d "$SAVE/verify" ] && cp -r "$SAVE/verify" .
git add -A scripts "${ALWAYS[@]}" $( [ -d verify ] && echo verify )
git commit -q -m "chore(verify): verify tooling and cross-stack fixes [skip ci]"

# Bug fixes found running verify/all (see .claude/handover/verify-findings.md), one commit each.
# A fix that no longer applies stops here: its stack PR has probably taken it, so drop the patch.
for patch in "$RES"/fixes/*.patch; do
  [ -e "$patch" ] || continue
  git am -q -3 "$patch" || { echo "Fix $(basename "$patch") does not apply (git am --abort to undo)" >&2; exit 1; }
done

# Generated API files: regenerate when this merge changed the API (the flux stack does not touch it today).
if ! git diff --quiet "$OPERATOR_TOP" HEAD -- nexus/api/app; then
  echo "nexus-api code differs from $OPERATOR_TOP: regenerate nexus/api/openapi.json and nexus/ui/src/api/schema.d.ts" >&2
fi
git log --oneline -4
