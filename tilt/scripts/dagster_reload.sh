#!/usr/bin/env bash
# Watch dagster/app for changes and reload the Dagster code location via the
# GraphQL API. docker_build_with_restart (tilt-restart-wrapper) handles the
# in-container gRPC process restart; we just need to tell the webserver to
# reconnect once it's back up.
set -euo pipefail

LOCATION=$1

while inotifywait -r -e modify,create,delete dagster/app; do
    echo "--- dagster/app changed, reloading code location '$LOCATION' ---"
    for i in $(seq 1 15); do
        result=$(curl -sf -X POST http://localhost:3000/graphql \
            -H 'Content-Type: application/json' \
            -d "{\"query\":\"mutation{reloadRepositoryLocation(repositoryLocationName:\\\"$LOCATION\\\"){__typename}}\"}" 2>/dev/null || true)
        if echo "$result" | grep -q "WorkspaceLocationEntry"; then
            echo "Code location '$LOCATION' reloaded"
            break
        fi
        echo "  waiting for gRPC server... ($i/15)"
        sleep 2
    done
done
