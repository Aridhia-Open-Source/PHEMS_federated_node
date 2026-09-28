#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Gitea Test Operations — repo creation, PRs, etc.
###############################################################################

source .dev.env

# Host-side script, so it needs the port-forwarded address (tilt maps this by
# default), not the in-cluster DNS name. The admin password is chart-generated,
# so fetch it from the secret rather than default to a value that won't match.
GITEA_URL="${GITEA_URL:-http://localhost:4000}"
GITEA_ADMIN_USER="${GITEA_ADMIN_USER:-gitea_admin}"
GITEA_ADMIN_PASS="${GITEA_ADMIN_PASS:-$(kubectl get secret gitea-admin -n "$NAMESPACE" -o jsonpath='{.data.password}' | base64 -d)}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
  cat <<EOF
Usage: $0 <command> [options]

Commands:
  token <user>              Get or create API token for user
  repo create <name>        Create a test repository
  pr create <repo> <title>  Create a pull request in repo
  setup                     Run full setup (create admin, test repo, PR)
  e2e [repo-name]           Full workflow: create repo, clone, commit, push, PR, merge

Examples:
  $0 token gitea_admin
  $0 repo create test-repo
  $0 pr create test-repo "Test PR"
  $0 setup
  $0 e2e
EOF
  exit 1
}

get_token() {
  local user=$1
  echo -e "${BLUE}Getting token for $user...${NC}" >&2

  # Gitea never returns the raw token value on list (only at creation time),
  # so there is no way to reuse a previously-created token here. Always
  # create a fresh one with a unique name to avoid name collisions on rerun.
  echo "Creating new token..." >&2
  local token
  token=$(curl -s -u "$GITEA_ADMIN_USER:$GITEA_ADMIN_PASS" \
    "$GITEA_URL/api/v1/users/$user/tokens" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"test-token-$(date +%s%N)\",\"scopes\":[\"write:repository\",\"write:user\"]}" | jq -r '.sha1')

  echo -e "${GREEN}Token created: $token${NC}" >&2
  echo "$token"
}

repo_exists() {
  local repo_name=$1
  curl -s -o /dev/null -w '%{http_code}' -u "$GITEA_ADMIN_USER:$GITEA_ADMIN_PASS" \
    "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$repo_name" | grep -q '^200$'
}

create_repo() {
  local repo_name=$1
  local token=$(get_token "$GITEA_ADMIN_USER")

  echo -e "${BLUE}Creating repository $repo_name...${NC}"

  curl -s -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/user/repos" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$repo_name\",\"description\":\"Test repository\",\"private\":false,\"auto_init\":true}" | jq .

  echo -e "${GREEN}Repository created: $GITEA_URL/$GITEA_ADMIN_USER/$repo_name${NC}"
}

create_pr() {
  local repo=$1
  local pr_title=$2
  local token=$(get_token "$GITEA_ADMIN_USER")

  echo -e "${BLUE}Creating PR in $repo...${NC}"

  # Create a test branch
  local branch_name="feature/test-$(date +%s)"
  echo "Creating branch $branch_name..."

  # Push a test file to new branch via API
  curl -s -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$repo/contents/test.txt" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"Add test file\",\"content\":\"dGVzdCBjb250ZW50\",\"branch\":\"$branch_name\"}" | jq .

  # Create PR
  local pr=$(curl -s -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$repo/pulls" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "{\"title\":\"$pr_title\",\"head\":\"$branch_name\",\"base\":\"main\"}" | jq .)

  local pr_num=$(echo "$pr" | jq -r '.number')
  local pr_url="$GITEA_URL/$GITEA_ADMIN_USER/$repo/pulls/$pr_num"

  echo -e "${GREEN}PR created: $pr_url${NC}"
  echo "$pr_url"
}

clone_commit_push() {
  local repo_name=$1
  local file_path="${2:-FEATURE.md}"
  local file_content="${3:-hello from e2e test at $(date -u)}"
  local branch_name="feature/test-$(date +%s)"
  local workdir="${CLAUDE_JOB_DIR:-/tmp}/tmp/gitea-e2e-$repo_name"
  local auth
  auth=$(printf '%s:%s' "$GITEA_ADMIN_USER" "$GITEA_ADMIN_PASS" | base64 -w0)

  rm -rf "$workdir"

  echo -e "${BLUE}Cloning $repo_name...${NC}" >&2
  git clone -c http.extraHeader="Authorization: Basic $auth" \
    "$GITEA_URL/$GITEA_ADMIN_USER/$repo_name.git" "$workdir" >&2

  git -C "$workdir" config http.extraHeader "Authorization: Basic $auth"
  git -C "$workdir" checkout -b "$branch_name" >&2

  mkdir -p "$(dirname "$workdir/$file_path")"
  echo "$file_content" > "$workdir/$file_path"
  git -C "$workdir" -c user.email="e2e-test@example.com" -c user.name="E2E Test" add "$file_path"
  git -C "$workdir" -c user.email="e2e-test@example.com" -c user.name="E2E Test" commit -m "Add $file_path via e2e test" >&2

  echo -e "${BLUE}Pushing $branch_name...${NC}" >&2
  git -C "$workdir" push origin "$branch_name" >&2

  echo "$branch_name"
}

merge_pr() {
  local repo=$1
  local pr_num=$2
  local token
  token=$(get_token "$GITEA_ADMIN_USER")

  echo -e "${BLUE}Merging PR #$pr_num in $repo...${NC}" >&2
  curl -sf -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$repo/pulls/$pr_num/merge" \
    -X POST \
    -H "Content-Type: application/json" \
    -d '{"Do":"merge"}'
}

e2e() {
  local repo_name="${1:-$TEST_TRIGGER_REPO}"
  local token
  token=$(get_token "$GITEA_ADMIN_USER")

  echo -e "${BLUE}=== 1/5 Create repo ===${NC}"
  curl -sf -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/user/repos" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$repo_name\",\"description\":\"e2e test repository\",\"private\":false,\"auto_init\":true}" | jq -r '.clone_url // .message'

  local default_branch
  default_branch=$(curl -sf -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$repo_name" | jq -r '.default_branch')
  echo "Default branch: $default_branch"

  echo -e "${BLUE}=== 2/5 Clone, commit, push ===${NC}"
  local branch_name
  branch_name=$(clone_commit_push "$repo_name")
  echo "Pushed branch: $branch_name"

  echo -e "${BLUE}=== 3/5 Create PR ===${NC}"
  local pr
  pr=$(curl -sf -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$repo_name/pulls" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "{\"title\":\"e2e test PR\",\"head\":\"$branch_name\",\"base\":\"$default_branch\"}")
  local pr_num
  pr_num=$(echo "$pr" | jq -r '.number')
  echo "PR #$pr_num created: $GITEA_URL/$GITEA_ADMIN_USER/$repo_name/pulls/$pr_num"

  echo -e "${BLUE}=== 4/5 Merge PR ===${NC}"
  merge_pr "$repo_name" "$pr_num"

  echo -e "${BLUE}=== 5/5 Verify merged ===${NC}"
  curl -sf -H "Authorization: token $token" \
    "$GITEA_URL/api/v1/repos/$GITEA_ADMIN_USER/$repo_name/pulls/$pr_num" | jq '{number, state, merged, merged_at}'

  echo -e "${GREEN}=== e2e workflow complete: $repo_name ===${NC}"
  echo "PR: $GITEA_URL/$GITEA_ADMIN_USER/$repo_name/pulls/$pr_num"
}

setup() {
  echo -e "${BLUE}=== Gitea Setup ===${NC}"

  # Wait for Gitea to be ready
  echo "Waiting for Gitea to be ready..."
  for i in {1..30}; do
    if curl -s "$GITEA_URL/api/v1/version" > /dev/null 2>&1; then
      echo -e "${GREEN}Gitea is ready${NC}"
      break
    fi
    echo "Attempt $i/30..."
    sleep 2
  done

  # Create test repo
  create_repo "test-repo"

  # Create test PR
  create_pr "test-repo" "Initial test PR"
}

# Main - guarded so other scripts can `source` this file to reuse its
# functions (get_token, clone_commit_push, merge_pr, repo_exists, ...)
# without triggering the CLI dispatch below.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  if [ $# -eq 0 ]; then
    usage
  fi

  case "$1" in
    token)
      if [ $# -lt 2 ]; then
        echo "Usage: $0 token <user>"
        exit 1
      fi
      get_token "$2"
      ;;
    repo)
      if [ $# -lt 3 ] || [ "$2" != "create" ]; then
        echo "Usage: $0 repo create <name>"
        exit 1
      fi
      create_repo "$3"
      ;;
    pr)
      if [ $# -lt 4 ] || [ "$2" != "create" ]; then
        echo "Usage: $0 pr create <repo> <title>"
        exit 1
      fi
      create_pr "$3" "$4"
      ;;
    setup)
      setup
      ;;
    e2e)
      e2e "${2:-}"
      ;;
    *)
      echo "Unknown command: $1"
      usage
      ;;
  esac
fi
