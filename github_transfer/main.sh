#!/usr/bin/env bash
set -euo pipefail

required_vars=(
  GH_OWNER
  GH_REPO
  GH_TOKEN
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

EPOCH_SECONDS=$(date +%s)
CLONE_TARGET_DIR="/tmp/repo"
BRANCH="${PR_NUMBER}-${PARENT_RUN_ID}-results"
GH_REPO_URI_PATH="${GH_OWNER}/${GH_REPO}"
GH_REPO_OUTPUT_PATH="${GH_RESULTS_DIR}/${PR_NUMBER}/${PARENT_RUN_ID}"
PARENT_ARTIFACT_PATH="${MNT_BASE_PATH}/${PARENT_RUN_ID}"
echo "Cloning repo $GH_REPO_URI_PATH"

rm -rf $CLONE_TARGET_DIR
gh repo clone "${GH_REPO_URI_PATH}" "${CLONE_TARGET_DIR}" -- --depth=1
(
    cd "${CLONE_TARGET_DIR}"
    git remote remove origin
    git remote add origin "https://$GH_TOKEN@github.com/${GH_REPO_URI_PATH}".git
    git fetch

    echo "Pulling or creating the results branch"
    if git checkout "${BRANCH}"; then
        git branch --set-upstream-to=origin/"${BRANCH}" "${BRANCH}"
        git pull
    else
        git checkout -b "${BRANCH}"
    fi

    mkdir -p $GH_REPO_OUTPUT_PATH
    zip -r "$GH_REPO_OUTPUT_PATH/archive.zip" $PARENT_ARTIFACT_PATH

    git add .
    git commit -am "PR${PR_NUMBER} - ${PARENT_RUN_ID} - results"

    git push --set-upstream origin "${BRANCH}" || git push
    echo "Changes pushed"
    rm -rf $CLONE_TARGET_DIR
)


echo "Completed"