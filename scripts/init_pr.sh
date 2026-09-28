#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Open a PR in the trigger-repository test repo (see init_repo.sh) containing
# a valid trigger-spec JSON file under the watched directory, so Dagster's
# PullRequestTriggerSensor has something real to pick up on merge.
###############################################################################

source .dev.env
source scripts/gitea.sh

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

token=$(get_token "$GITEA_ADMIN_USER")

default_branch=$(curl -sf -H "Authorization: token $token" \
  "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO" | jq -r '.default_branch')

spec_file="${TEST_TRIGGER_REPO_WATCH_DIR}trigger-$(date +%s).json"
spec_content='{"spec": {"image": "busybox:1.36", "env": {"TEST_VAR": "test-value"}}}'

echo -e "${BLUE}=== 1/2 Commit trigger spec and push ===${NC}"
branch_name=$(clone_commit_push "$TEST_TRIGGER_REPO" "$spec_file" "$spec_content")
echo "Pushed branch: $branch_name"
echo "Trigger file: $spec_file"

echo -e "${BLUE}=== 2/2 Create PR ===${NC}"
pr=$(curl -sf -H "Authorization: token $token" \
  "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO/pulls" \
  -X POST \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"Trigger: $spec_file\",\"head\":\"$branch_name\",\"base\":\"$default_branch\"}")
pr_num=$(echo "$pr" | jq -r '.number')

echo
echo -e "${BLUE}=== Fresh GET: pull request ===${NC}"
curl -sf -H "Authorization: token $token" \
  "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO/pulls/$pr_num" \
  | jq '{number, title, state, head: .head.ref, base: .base.ref, merged, html_url}'

echo
echo -e "${GREEN}=== init_pr complete ===${NC}"
echo "PR page: $GITEA_URL/$GITEA_ADMIN_USER/$TEST_TRIGGER_REPO/pulls/$pr_num"
