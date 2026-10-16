#!/usr/bin/env bash
# Admin user, token, org, normal repo. Token is written to /tmp/m0/token (never printed).
set -eu; . "$(dirname "$0")/common.sh"
docker exec -u git $CN gitea admin user create --admin --username $ADM --password 'Spike-pass-1234' --email spikeadmin@example.com --must-change-password=false 2>&1 | tail -1
docker exec -u git $CN gitea admin user generate-access-token --username $ADM --scopes all --raw > /tmp/m0/token
TOKEN=$(cat /tmp/m0/token)
api POST /orgs '{"username":"'$ORG'","visibility":"private"}' | cut -c1-300
api POST /orgs/$ORG/repos '{"name":"'$REPO'","auto_init":false,"private":true,"default_branch":"master"}' | cut -c1-300
