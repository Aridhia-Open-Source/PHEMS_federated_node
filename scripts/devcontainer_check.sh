#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Checks the dev container (.devcontainer/) without VS Code: builds and starts it with the
# devcontainer CLI (a mise tool), which runs its features and `mise run setup` as VS Code
# does, then checks the vscode user can reach the host's Docker from inside. Removes the
# container afterwards; its image and the fn-mise-data volume stay.
#
#   mise run devcontainer-check
####################################################################################

cd "$(dirname "$0")/.."

# Its own label, so a container VS Code made for this folder is left alone
LABEL="fn-devcontainer-check=$(basename "$PWD")"
remove() { docker ps -aq --filter "label=$LABEL" | xargs -r docker rm -f > /dev/null; }
trap remove EXIT

devcontainer up --workspace-folder . --id-label "$LABEL" --remove-existing-container
devcontainer exec --workspace-folder . --id-label "$LABEL" docker ps > /dev/null
devcontainer exec --workspace-folder . --id-label "$LABEL" kind version
echo "dev container: built, set up, and Docker works inside"
