#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Merge a PR (by number) in the trigger-repository test repo (see
# init_repo.sh / init_pr.sh), triggering Dagster's PullRequestTriggerSensor.
###############################################################################

source .dev.env
source scripts/gitea.sh

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

if [ $# -lt 1 ]; then
  echo "Usage: $0 <pr_number>"
  exit 1
fi
pr_num=$1

token=$(get_token "$GITEA_ADMIN_USER")

merge_pr "$TEST_TRIGGER_REPO" "$pr_num"

echo -e "${BLUE}=== Fresh GET: pull request ===${NC}"
curl -sf -H "Authorization: token $token" \
  "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO/pulls/$pr_num" \
  | jq '{number, title, state, merged, merged_at, html_url}'

echo
echo -e "${GREEN}=== merge_pr complete ===${NC}"
echo "PR page: $GITEA_URL/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO/pulls/$pr_num"
