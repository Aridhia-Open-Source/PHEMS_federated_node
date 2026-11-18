#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Push this working tree to a repository in the dev cluster's Gitea, so the release workflow
# (.gitea/workflows/release.yml) has source to build. Uncommitted changes to tracked files go too,
# as one commit on top of HEAD; untracked files do not.
#
# Usage:
#   ./scripts/mirror_to_gitea.sh                       # push to main only
#   ./scripts/mirror_to_gitea.sh --tag v0.0.1-dev      # and tag it: the tag starts a release
#   ./scripts/mirror_to_gitea.sh --repo NAME --tag v0.0.2-dev
# Run it twice with two tags for two builds of one commit (the revert run in GitOps-Delivery.md).
###############################################################################

source .dev.env
source scripts/gitea_lib.sh

REPO=federated-node
TAG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    *) echo "usage: $0 [--repo NAME] [--tag vX.Y.Z]" >&2; exit 2 ;;
  esac
done
if [ -n "$TAG" ] && [ "${TAG#v}" = "$TAG" ]; then
  echo "--tag must start with v (the workflow runs on v*): $TAG" >&2
  exit 2
fi

gitea_connect

echo "=== Gitea repository $GITEA_ADMIN_USER/$REPO ============================="
echo "repository: $(gitea_ensure_repo "$REPO")"

# The working tree as a commit on HEAD, or HEAD itself when it is clean
REV=HEAD
STASH="$(git stash create)"
if [ -n "$STASH" ]; then
  REV="$(git commit-tree "$STASH^{tree}" -p HEAD -m "Working tree of $(git rev-parse --short HEAD)")"
  echo "uncommitted changes pushed as $REV"
fi

REFSPECS=("+$REV:refs/heads/main")
[ -n "$TAG" ] && REFSPECS+=("+$REV:refs/tags/$TAG")

echo
echo "=== Pushing ================================================================"
gitea_git push "$(gitea_repo_url "$REPO")" "${REFSPECS[@]}"

echo
echo "Pushed $(git rev-parse --short "$REV") to $GITEA_URL/$GITEA_ADMIN_USER/$REPO"
if [ -n "$TAG" ]; then
  echo "Release run: $GITEA_URL/$GITEA_ADMIN_USER/$REPO/actions"
  echo "When it is green:"
  echo "  helm show chart oci://localhost:5001/charts/federated-node --version ${TAG#v} --plain-http"
fi
