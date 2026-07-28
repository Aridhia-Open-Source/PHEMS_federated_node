#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Full cluster teardown and redeploy
###############################################################################

echo
echo "=== NUKING CLUSTER =========================================================="
echo "This will delete the cluster, registries, and redeploy everything"
echo

./scripts/cluster.sh down

./scripts/teardown.sh

echo
echo "=== BRINGING CLUSTER BACK UP =============================================="
echo

./scripts/cluster.sh up

echo
echo "=== DEPLOYING APPLICATION =================================================="
echo

./scripts/deploy.sh

echo
echo "=== DEPLOYMENT COMPLETE ==================================================="
echo
