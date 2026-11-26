#!/usr/bin/env bash
# Collect what a QC ticket writer needs to know about a change, as markdown on stdout.
#
#   gather.sh 664                                 one pull request
#   gather.sh origin/main..origin/verify/all      every PR in a range, merged or stacked
#   gather.sh origin/verify/all                   the same as origin/main..origin/verify/all
#   gather.sh                                     the current branch's PR, else origin/main..HEAD
#
# Needs git, gh (logged in) and jq. Read only: it never writes to GitHub.
# In CI, check out with fetch-depth: 0 so ranges have their history.
set -euo pipefail

die() { echo "gather.sh: $*" >&2; exit 1; }

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner) || die "gh cannot see the repository (gh auth login?)"
OWNER=${REPO%/*}
NAME=${REPO#*/}
CACHE=$(mktemp -d)
trap 'rm -rf "$CACHE"' EXIT
git fetch -q origin 2>/dev/null || echo "(git fetch origin failed, using local refs)" >&2

# Drop the PR template's own boilerplate (the self-assessment checklist and the empty
# Yes/No/N/A table). Real checklists and test steps stay. Bodies are quoted so their
# headings do not clash with this file's.
TEMPLATE='Checked for new dependencies|Added test$|Coverage stable|Updated \[?Changelog|Please try to keep this updated|\|\|\|$|^\|Action\|'
clean() { { grep -vE "$TEMPLATE" || true; } | sed 's/^/> /'; }
cut_body() {
  if [[ ${BODY_CHARS:-0} -gt 0 ]]; then
    jq -Rrs --argjson n "$BODY_CHARS" 'if length > $n then .[0:$n] + "\n> [...cut]" else . end'
  else cat; fi
}

# One PR or issue by number, cached. Prints the JSON, or "null" when the number does not exist.
lookup() {
  local f="$CACHE/$1.json" out
  if [[ ! -f $f ]]; then
    out=$(gh api graphql -F n="$1" -f o="$OWNER" -f r="$NAME" -f query='
      query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){issueOrPullRequest(number:$n){
        __typename
        ... on Issue{number title state body}
        ... on PullRequest{number title state body baseRefName headRefName mergedAt
          mergeCommit{oid}
          closingIssuesReferences(first:20){nodes{number repository{nameWithOwner}}}}}}}' 2>&1) || {
      if grep -q "Could not resolve to an issue or pull request" <<<"$out"; then echo null > "$f"; cat "$f"; return; fi
      die "GitHub lookup of #$1 failed: $out"
    }
    jq '.data.repository.issueOrPullRequest' <<<"$out" > "$f"
  fi
  cat "$f"
}

# Issue and PR numbers a body mentions: #123 and full links to this repo.
mentions() {
  { grep -oE "(^|[^&A-Za-z0-9/])#[0-9]+|github\.com/$REPO/(issues|pull)/[0-9]+" || true; } | grep -oE '[0-9]+$' || true
}

# What a PR links to: closing issues in this repo, then numbers its body mentions.
linked() {
  local json; json=$(lookup "$1")
  { jq -r --arg repo "$REPO" '.closingIssuesReferences.nodes[]? | select(.repository.nameWithOwner == $repo) | .number' <<<"$json"
    jq -r '.body // ""' <<<"$json" | mentions; } | { grep -vx "$1" || true; } | sort -un
}

PRS=" "
SEEN=" "
in_range() { [[ $PRS == *" $1 "* ]]; }

describe() {
  local n=$1 json
  json=$(lookup "$n")
  echo "## #$n: $(jq -r .title <<<"$json")"
  echo
  jq -r '"\(.__typename), \(.state)" + (if .baseRefName then ", \(.headRefName) -> \(.baseRefName)" else "" end)' <<<"$json"
  echo
  jq -r '.body // ""' <<<"$json" | clean | cut_body
  echo
  local refs=() i ij links
  links=$(linked "$n") || exit 1
  for i in $links; do
    ij=$(lookup "$i")
    [[ $ij == null ]] && continue
    if [[ $(jq -r .__typename <<<"$ij") == PullRequest ]]; then
      # Linked PRs are context only: one line, never their bodies
      refs+=("#$i $(jq -r '.title + " (" + .state + ")"' <<<"$ij")$(in_range "$i" && echo ', in this range' || true)")
    elif [[ $SEEN == *" $i "* ]]; then
      refs+=("#$i $(jq -r .title <<<"$ij") (issue, printed above)")
    else
      SEEN+="$i "
      echo "### Linked issue #$i: $(jq -r '.title + " (" + .state + ")"' <<<"$ij")"
      echo
      jq -r '.body // ""' <<<"$ij" | clean | cut_body
      echo
    fi
  done
  if ((${#refs[@]})); then
    echo "Also mentions:"
    printf -- '- %s\n' "${refs[@]}"
    echo
  fi
}

# File paths on stdin, counted by their first two folders.
areas() {
  echo "## Files changed, by area"
  echo
  local counts; counts=$(awk -F/ '{ if (NF>2) print $1"/"$2; else print $1 }' | sort | uniq -c | sort -rn)
  sed -n '1,40p' <<<"$counts"
  if (( $(wc -l <<<"$counts") > 40 )); then echo "(showing 40 of $(wc -l <<<"$counts") areas)"; fi
  echo
}

# Lines on stdin, the first $1 of them, saying when some were left out.
first() {
  local lines; lines=$(cat)
  [[ -z $lines ]] && { echo "(none)"; return; }
  sed -n "1,${1}p" <<<"$lines"
  if (( $(wc -l <<<"$lines") > $1 )); then echo "(showing $1 of $(wc -l <<<"$lines"))"; fi
}

# The build to test, where the repo describes its tests and QA plans, and the open QC tickets.
footer() {
  local ref=$1 chart
  echo "## Ref under test"
  echo
  echo "Commit: $(git rev-parse --short "$ref") ($2)"
  echo "$3"
  echo "See what changed: $4"
  chart=$(git show "$ref:k8s/federated-node/Chart.yaml" 2>/dev/null | sed -n 's/^version: *//p' || true)
  echo "Chart version at that commit: ${chart:-unknown}"
  echo
  echo "## Test notes and QA plans at that commit"
  echo
  git ls-tree -r --name-only "$ref" \
    | { grep -iE '(e2e|end-to-end).*README\.md$|(^|/)TESTING\.md$|^project/QA/.*\.md$' || echo "(none found)"; }
  echo
  if git cat-file -e "$ref:nexus/api/app/__init__.py" 2>/dev/null; then
    echo "## Routes nexus-api registers at that commit"
    echo
    python3 -I "$(dirname "$0")/routes.py" "$ref"
    echo
  fi
  echo "## Open [QC] issues"
  echo
  gh issue list --state open --search "QC in:title" --limit 200 --json number,title \
    -q '.[] | select(.title | startswith("[QC]") or startswith("[Draft] [QC]")) | "- #\(.number) \(.title)"' | first 200
  echo
}

verify_ref() { git rev-parse --verify -q "$1^{commit}" >/dev/null || die "unknown ref '$1' (try origin/$1)"; }

arg=${1:-}
if [[ -z $arg ]]; then
  if n=$(gh pr view --json number -q .number 2>/dev/null); then arg=$n
  else arg=origin/main..HEAD; fi
fi

# --- one pull request --------------------------------------------------------------------------

if [[ $arg =~ ^[0-9]+$ ]]; then
  json=$(lookup "$arg")
  [[ $json != null && $(jq -r .__typename <<<"$json") == PullRequest ]] || die "#$arg is not a pull request in $REPO"
  PRS=" $arg "
  describe "$arg"
  echo "## Commits"; echo
  commits=$(gh api --paginate "repos/$REPO/pulls/$arg/commits" -q '.[].commit.message | split("\n")[0] | "- " + .')
  first 150 <<<"$commits"
  echo
  named=$( { grep -oE '#[0-9]+' <<<"$commits" || true; } | { grep -vx "#$arg" || true; } | sort -u | tr '\n' ' ')
  if [[ -n $named ]]; then echo "PRs and issues named in its commits: $named"; echo; fi
  gh api --paginate "repos/$REPO/pulls/$arg/files" -q '.[].filename' | areas
  into=$(jq -r .baseRefName <<<"$json")
  if [[ $(jq -r .mergedAt <<<"$json") != null ]]; then
    ref=$(jq -r .mergeCommit.oid <<<"$json"); why="the merge commit"
    git cat-file -e "$ref^{commit}" 2>/dev/null || git fetch -q origin "$ref" || die "cannot fetch merge commit $ref"
    diffcmd="git diff $(git rev-parse --short "$ref")^1 $(git rev-parse --short "$ref") -- <path>"
  else
    git fetch -q origin "refs/pull/$arg/head" || die "cannot fetch the head of #$arg"
    ref=$(git rev-parse FETCH_HEAD); why="the PR head, not merged yet"
    diffcmd="git diff origin/$into...$(git rev-parse --short "$ref") -- <path>"
  fi
  footer "$ref" "$why" "Merges into: $into" "$diffcmd"
  exit 0
fi

# --- a range -----------------------------------------------------------------------------------

[[ $arg == *..* ]] || arg="origin/main..$arg"
base=${arg%%..*}; head=${arg##*..}; base=${base%.}
verify_ref "$base"; verify_ref "$head"
BODY_CHARS=${BODY_CHARS:-1500}

# Numbers named in commit subjects that are not already on the base (--cherry-pick drops
# commits that were copied over under a new SHA), then PRs merged by branch, in any state:
# their head or merge commit is inside the range and not on the base.
from_subjects=$(git log --cherry-pick --right-only --format=%s "$base...$head" | { grep -oE '#[0-9]+' || true; } | tr -d '#')
inside() { git cat-file -e "$1^{commit}" 2>/dev/null && git merge-base --is-ancestor "$1" "$head" && ! git merge-base --is-ancestor "$1" "$base"; }
from_heads=$(gh pr list --state all --limit 2000 --json number,headRefOid,mergeCommit \
               -q '.[] | "\(.number) \(.headRefOid) \(.mergeCommit.oid // "-")"' |
  while read -r n sha merge; do
    if inside "$sha" || { [[ $merge != - ]] && inside "$merge"; }; then echo "$n"; fi
  done)
RELEASED=""; ISSUES=""
for n in $(printf '%s\n%s\n' "$from_subjects" "$from_heads" | { grep -E '^[0-9]+$' || true; } | sort -un); do
  json=$(lookup "$n")
  [[ $json == null ]] && continue
  if [[ $(jq -r .__typename <<<"$json") == Issue ]]; then ISSUES+="#$n "; continue; fi
  oid=$(jq -r '.mergeCommit.oid // empty' <<<"$json")
  if [[ -n $oid ]] && git cat-file -e "$oid^{commit}" 2>/dev/null && git merge-base --is-ancestor "$oid" "$base"; then
    RELEASED+="#$n "; continue
  fi
  PRS+="$n "
done

echo "# Range $base..$head"
echo
echo "$(wc -w <<<"$PRS") pull requests. Bodies are cut at $BODY_CHARS characters; read a whole one with gh pr view <n>."
echo
echo "## Index"
echo
for n in $PRS; do
  jq -r '"- #\(.number) \(.title) (\(.state), into \(.baseRefName))"' "$CACHE/$n.json"
done
echo
if [[ -n $RELEASED ]]; then echo "Already on $base, left out: $RELEASED"; echo; fi
if [[ -n $ISSUES ]]; then echo "Issues named in commit subjects: $ISSUES"; echo; fi
for n in $PRS; do describe "$n"; done
echo "## Commits on the branch itself with no PR number"; echo
git log --first-parent --cherry-pick --right-only --no-merges --format='- %s' "$base...$head" \
  | { grep -vE '#[0-9]+' || true; } | first 80
echo
git diff --name-only "$base...$head" | areas
git diff --shortstat "$base...$head"
echo
open=$(for n in $PRS; do jq -r 'select(.state == "OPEN") | "#\(.number)"' "$CACHE/$n.json"; done | tr '\n' ' ')
footer "$head" "the head of the range" "Still open in this range: ${open:-(none)}" "git diff $base...$head -- <path>"
