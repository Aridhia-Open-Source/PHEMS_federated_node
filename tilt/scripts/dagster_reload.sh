#!/usr/bin/env bash
# Keeps the Dagster webserver's code location loaded while Tilt rebuilds and restarts the code
# server, and prints the dev URLs each time the location (re)loads.
#
# It polls the webserver instead of watching dagster/app, which is what this script used to do:
# - A rebuild or a replaced pod (Dockerfile, pyproject.toml or Tiltfile changed, a rebase)
#   touches nothing under dagster/app, so a file watcher never fires.
# - Even on a live update the watcher fires when the file is saved, before Tilt has synced it
#   and restarted the process. The reload hit the old server, or the new one while it was
#   still starting (about 6s before it serves).
# - reloadRepositoryLocation answers with a WorkspaceLocationEntry even when the load failed;
#   the failure is inside locationOrLoadError. The old check took that for success.
# The webserver watches the code server and reloads by itself when it comes back with a new
# server id, but gives up after 10 failed reconnects (MAX_RECONNECT_ATTEMPTS in dagster's
# _grpc/server_watcher.py) and then shows "Could not reach user code server" until someone
# reloads the location. Here that someone is this script.
#
# Usage: dagster_reload.sh LOCATION
# Env:   DEV_URLS    lines to print when the location loads (set by the Tiltfile)
#        DAGSTER_URL the Dagster webserver, default http://localhost:3000

# No set -e: a failed curl must not end the loop, and Tilt does not start a serve_cmd again.
set -u

LOCATION=$1
GRAPHQL="${DAGSTER_URL:-http://localhost:3000}/graphql"
URLS="${DEV_URLS:-}"
TIMEOUT=60    # seconds a reload is retried before the failure is reported
POLL=3        # seconds between checks while the location is loaded
SLOW_POLL=15  # seconds between quiet retries after giving up

SELECTION='__typename ... on PythonError { message } ... on WorkspaceLocationEntry { locationOrLoadError { __typename ... on RepositoryLocation { serverId } ... on PythonError { message } } }'
STATUS='query($name: String!) { workspaceLocationEntryOrError(name: $name) { '"$SELECTION"' } }'
RELOAD='mutation($name: String!) { reloadRepositoryLocation(repositoryLocationName: $name) { '"$SELECTION"' } }'

RESPONSE=""
ID=""   # server id of the loaded location, empty when it is not loaded
ERR=""  # first line of why it is not loaded

call() {  # $1 = GraphQL document taking $name
    jq -n -c --arg q "$1" --arg name "$LOCATION" '{query: $q, variables: {name: $name}}' |
        curl -s --max-time 30 -X POST "$GRAPHQL" -H 'Content-Type: application/json' --data-binary @-
}

# Loaded means locationOrLoadError is a RepositoryLocation, the only answer that has a serverId.
parse() {
    ID=$(jq -r '.data[]? | (.locationOrLoadError // .) | .serverId // empty' <<< "$RESPONSE" 2>/dev/null)
    ERR=$(jq -r '.data[]? | (.locationOrLoadError // .) | (.message // "" | split("\n")[0]) // empty' <<< "$RESPONSE" 2>/dev/null)
}

check() {
    RESPONSE=$(call "$STATUS")
    parse
}

reload() {
    RESPONSE=$(call "$RELOAD")
    parse
}

reload_until_loaded() {
    local deadline=$((SECONDS + TIMEOUT))
    while (( SECONDS < deadline )); do
        reload
        [[ -n $ID ]] && return 0
        sleep 2
    done
    return 1
}

print_urls() {
    [[ -z $URLS ]] || printf '\nDev URLs:\n%s\n\n' "$URLS"
}

announced=""  # server id the URLs were last printed for
gave_up=0

while true; do
    check
    if [[ -z $ID ]]; then
        if (( gave_up )); then
            reload  # quiet retry, the failure was reported
        else
            echo "Code location '$LOCATION' is not loaded (${ERR:-no answer from $GRAPHQL}), reloading..."
            if ! reload_until_loaded; then
                echo "ERROR: code location '$LOCATION' is still not loaded after ${TIMEOUT}s: ${ERR:-no answer from $GRAPHQL}"
                echo "       Check the code server pod log. Retrying every ${SLOW_POLL}s."
                gave_up=1
            fi
        fi
    fi

    if [[ -n $ID ]]; then
        gave_up=0
        if [[ $ID != "$announced" ]]; then
            echo "Code location '$LOCATION' loaded (code server $ID)"
            print_urls
            announced=$ID
        fi
    fi

    if (( gave_up )); then
        sleep "$SLOW_POLL"
    else
        sleep "$POLL"
    fi
done
