#!/usr/bin/env bash
set -euo pipefail

required_vars=(
  GH_OWNER
  GH_REPO
  GH_TOKEN
  GH_BASE_BRANCH
  GH_RESULTS_DIR
  MNT_BASE_PATH
  PARENT_RUN_ID
  PR_NUMBER
)

for var in "${required_vars[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo "${var} not set"
    exit 1
  fi
done

CLONE_TARGET_DIR="/tmp/repo"
BRANCH="${PR_NUMBER}-${PARENT_RUN_ID}-results"
GH_REPO_URI_PATH="${GH_OWNER}/${GH_REPO}"
GH_REPO_OUTPUT_PATH="${GH_RESULTS_DIR}/${PR_NUMBER}/${PARENT_RUN_ID}"
PARENT_ARTIFACT_PATH="${MNT_BASE_PATH}/${PARENT_RUN_ID}"

echo "Cloning repo ${GH_REPO_URI_PATH}"

rm -rf "${CLONE_TARGET_DIR}"

gh repo clone "${GH_REPO_URI_PATH}" "${CLONE_TARGET_DIR}" -- --depth=1

(
  cd "${CLONE_TARGET_DIR}"

  # Configure commit identity locally
  git config user.name "phems-bot"
  git config user.email "phem-federated-node@users.noreply.github.com"

  # Replace origin with token-auth remote
  git remote remove origin
  git remote add origin "https://${GH_TOKEN}@github.com/${GH_REPO_URI_PATH}.git"
  git fetch origin

  echo "Checking if results branch already exists on remote"

  if git ls-remote --exit-code --heads origin "${BRANCH}" > /dev/null 2>&1; then
    echo "ERROR: Results branch ${BRANCH} already exists on remote."
    exit 1
  fi

  git checkout -b "${BRANCH}"

  mkdir -p "${GH_REPO_OUTPUT_PATH}"

  echo "Creating archive from ${PARENT_ARTIFACT_PATH}"

  (
    cd "${PARENT_ARTIFACT_PATH}"
    zip -r "${CLONE_TARGET_DIR}/${GH_REPO_OUTPUT_PATH}/archive.zip" .
  )

  git add .

  git commit -m "PR${PR_NUMBER} - ${PARENT_RUN_ID} - results"
  git push --set-upstream origin "${BRANCH}"

  echo "Results branch pushed successfully"

  echo "Creating pull request"

  gh pr create \
    --repo "${GH_REPO_URI_PATH}" \
    --head "${BRANCH}" \
    --base "${GH_BASE_BRANCH}" \
    --title "PR${PR_NUMBER} - results" \
    --body "Automated results for PR #${PR_NUMBER}, run ${PARENT_RUN_ID}"
)

rm -rf "${CLONE_TARGET_DIR}"

echo "Completed"