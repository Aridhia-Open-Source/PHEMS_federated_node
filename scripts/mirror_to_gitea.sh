#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Mirror a site repository into the cluster's Gitea, so Flux pulls from inside the cluster (ADR 0031).
# Gitea pulls from the site repository on a timer (a pull mirror); nothing pushes into the cluster.
#
# Usage:
#   SITE_REPO_TOKEN=... ./scripts/mirror_to_gitea.sh https://github.com/org/site-repo.git
#   ./scripts/mirror_to_gitea.sh   # the mirror exists: sync it now, without waiting for the interval
#
# Env:
#   SITE_REPO_TOKEN   read token for a private site repository (never on the command line)
#   SITE_REPO_USER    username sent with the token (default: git; GitHub accepts any)
#   MIRROR_NAME       repository name in Gitea (default: fn-site, the one `mise run flux up` points Flux at)
#   MIRROR_INTERVAL   how often Gitea pulls (default: 10m, the shortest Gitea allows by default)
#
# Then `mise run flux up` finds fn-site there and points Flux at it.
###############################################################################

SOURCE_URL="${1:-}"
MIRROR_NAME="${MIRROR_NAME:-fn-site}"
MIRROR_INTERVAL="${MIRROR_INTERVAL:-10m}"

source scripts/load_env.sh
source scripts/gitea_lib.sh

gitea_connect

if EXISTING="$(gitea_api GET "/repos/$GITEA_ADMIN_USER/$MIRROR_NAME" 2>/dev/null)"; then
  if [ "$(jq -r .mirror <<<"$EXISTING")" != true ]; then
    echo "$GITEA_ADMIN_USER/$MIRROR_NAME exists and is not a mirror: mise run flux down deletes it" >&2
    exit 1
  fi
  gitea_api POST "/repos/$GITEA_ADMIN_USER/$MIRROR_NAME/mirror-sync" >/dev/null
  echo "Mirror $GITEA_ADMIN_USER/$MIRROR_NAME of $(jq -r .original_url <<<"$EXISTING"): sync started"
  exit 0
fi

if [ -z "$SOURCE_URL" ]; then
  echo "usage: [SITE_REPO_TOKEN=...] $0 SITE_REPO_URL" >&2
  exit 2
fi

# jq builds the body, so the token is escaped and never on a command line
jq -n \
  --arg url "$SOURCE_URL" \
  --arg name "$MIRROR_NAME" \
  --arg owner "$GITEA_ADMIN_USER" \
  --arg interval "$MIRROR_INTERVAL" \
  --arg user "${SITE_REPO_USER:-git}" \
  --arg token "${SITE_REPO_TOKEN:-}" \
  '{clone_addr: $url, repo_name: $name, repo_owner: $owner, service: "git", mirror: true,
    mirror_interval: $interval, private: true}
   + (if $token == "" then {} else {auth_username: $user, auth_password: $token} end)' \
  | gitea_api POST /repos/migrate -d @- >/dev/null

echo "Mirrored $SOURCE_URL as $GITEA_URL/$GITEA_ADMIN_USER/$MIRROR_NAME, pulled every $MIRROR_INTERVAL"
echo "Next: mise run flux up (Flux pulls from the mirror)"
