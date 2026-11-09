#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Idempotently create what the other trigger-simulation scripts (init_pr.sh,
# merge_pr.sh, get_project.sh) build on: the Gitea repos, the nexus-api project,
# the global secrets, repositories and dataset, and the project's resources.
# That is `fncli apply` of the dev project's node file, bootstrap/examples/e2e.yaml
# (the TEST_* names of .dev.env), which needs fncli installed with pipx.
###############################################################################

cd "$(dirname "$0")/.."

fncli apply -f examples/e2e.yaml -y
