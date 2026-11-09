#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Idempotently create what the other trigger-simulation scripts (init_pr.sh,
# merge_pr.sh, get_project.sh) build on: the Gitea repos, the nexus-api project,
# the global secrets, repositories and dataset, and the project's resources.
# That is `fncli apply` of the dev project's node files, bootstrap/examples/globals-e2e.yaml and projects/e2e.yaml
# (the TEST_* names of .dev.env), on the node of bootstrap/examples/context.yaml. It needs fncli installed with pipx.
###############################################################################

cd "$(dirname "$0")/.."

export FNCLI_CONTEXT=examples/context.yaml
fncli apply -f examples/globals-e2e.yaml -y
fncli apply -f examples/projects/e2e.yaml -y
