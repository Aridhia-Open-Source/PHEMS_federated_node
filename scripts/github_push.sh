#!/usr/bin/env bash
set -euo pipefail

CLONE_TARGET_DIR="/tmp/repo"
RUN_ID=$1


if [ -z "$GH_RESULTS_DIR" ]; then
    echo "GH_RESULTS_DIR not provided"
    exit 1
fi

if [ -z "$ARTIFACT_PATH" ]; then
    echo "ARTIFACT_PATH not provided"
    exit 1
fi

if [ -z "$RUN_ID" ]; then
    echo "RUN_ID not provided"
    exit 1
fi

if [ -z "$GH_TOKEN" ]; then
    echo "GH_TOKEN env not set"
    exit 1
fi

EPOCH_SECONDS=$(date +%s)
BRANCH="${RUN_ID}-${EPOCH_SECONDS}-results"
PROJ_DIR=$PWD

# echo "Cloning repo"
rm -rf $CLONE_TARGET_DIR
gh repo clone "${GH_OWNER}/${GH_REPO}" "${CLONE_TARGET_DIR}" -- --depth=1
(
    cd "${CLONE_TARGET_DIR}" || exit
    git remote remove origin
    git remote add origin "https://$GH_TOKEN@github.com/${GH_OWNER}/${GH_REPO}".git
    git fetch

    echo "Pulling or creating the results branch"
    if git checkout "${BRANCH}"; then
        git branch --set-upstream-to=origin/"${BRANCH}" "${BRANCH}"
        git pull
    else
        git checkout -b "${BRANCH}"
    fi

    mkdir -p "${GH_RESULTS_DIR}/${RUN_ID}"

    zip -r "${GH_RESULTS_DIR}/${RUN_ID}/archive.zip" "${PROJ_DIR}/$ARTIFACT_PATH"

    git add .
    git commit -am "${RUN_ID} Results"

    git push --set-upstream origin "${BRANCH}" || git push
    echo "Changes pushed"
)


echo "Completed"