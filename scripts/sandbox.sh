#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Federated Node - dev sandbox
#
# A throwaway Debian 13 laptop in Docker (scripts/sandbox/Dockerfile) with its own
# Docker daemon, for testing scripts/install-dev.sh as a fresh clone would run it.
# Your own Docker, kind cluster, registries and ports are never touched; the services
# are only reachable inside the sandbox.
#
#   ./scripts/sandbox.sh up          # create it if needed, copy the working tree in, run
#                                    #   the installer (again: syncs and reinstalls)
#   ./scripts/sandbox.sh down        # remove it and its volumes
#   ./scripts/sandbox.sh shell       # a shell in the repo copy
#   ./scripts/sandbox.sh <cmd...>    # run any command there, e.g. fncli project-show
#
# Via make: make sandbox up|down|shell, and SANDBOX=1 make <target> for any target.
#
# The copy is the working tree minus gitignored files, so .dev.env, dev.values.yaml
# and charts/ start missing, as in a clone. The code Tilt watches (LIVE_DIRS) is
# bind-mounted instead, so host edits live-reload in the sandbox. Anything else reaches
# it on the next `up`. The mounts are fixed when the sandbox is created: down, then up.
####################################################################################

cd "$(dirname "$0")/.."

NAME=fn-sandbox
IMAGE=fn-sandbox:latest
VOLUMES=(fn-sandbox-docker fn-sandbox-containerd)
REPO=/home/dev/fn
# Tilt's docker_build contexts (Tiltfile), mounted from the host for live reload.
LIVE_DIRS=(webserver dagster)
DEV_PATH=/home/dev/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

TTY=(-i)
[ -t 0 ] && [ -t 1 ] && TTY=(-it)

as_dev() {
  docker exec "${TTY[@]}" -u dev -w "$REPO" \
    -e USER=dev -e HOME=/home/dev -e PATH="$DEV_PATH" "$NAME" "$@"
}

require_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2> /dev/null || true)" = "true" ] || {
    echo "No sandbox running. Start it with: make sandbox up" >&2
    exit 1
  }
}

case "${1:-}" in
  up)
    docker build -t "$IMAGE" -f scripts/sandbox/Dockerfile scripts
    if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2> /dev/null || true)" != "true" ]; then
      docker rm -f "$NAME" > /dev/null 2>&1 || true
      mounts=()
      for dir in "${LIVE_DIRS[@]}"; do mounts+=(-v "$PWD/$dir:$REPO/$dir"); done
      docker run -d --init --privileged --name "$NAME" --hostname "$NAME" \
        -v fn-sandbox-docker:/var/lib/docker \
        -v fn-sandbox-containerd:/var/lib/containerd \
        "${mounts[@]}" \
        "$IMAGE" > /dev/null
      echo "Waiting for the sandbox's Docker daemon..."
      for _ in $(seq 1 90); do
        docker exec "$NAME" docker info > /dev/null 2>&1 && break
        sleep 1
      done
      docker exec "$NAME" docker info > /dev/null
    fi

    echo "Copying the working tree to $REPO in the sandbox..."
    live_re="^($(IFS='|'; echo "${LIVE_DIRS[*]}"))/"
    git ls-files -z --cached --others --exclude-standard --deduplicate \
      | grep -zEv "$live_re" \
      | tar --null -T - --ignore-failed-read -cf - 2> /dev/null \
      | docker exec -i -u dev "$NAME" tar -xf - -C "$REPO"
    # A clone has a .git and deploy.sh asks git for the branch and sha.
    docker exec -u dev -w "$REPO" "$NAME" sh -c \
      'git init -q -b sandbox 2>/dev/null; git add -A && git -c user.name=sandbox -c user.email=sandbox@localhost commit -qm sync --allow-empty'

    as_dev ./scripts/install-dev.sh
    ;;

  down)
    docker rm -f "$NAME" > /dev/null 2>&1 || true
    docker volume rm "${VOLUMES[@]}" > /dev/null 2>&1 || true
    echo "Sandbox removed."
    ;;

  shell)
    require_running
    TTY=(-it)
    as_dev bash -l
    ;;

  "")
    echo "Usage: $0 <up|down|shell|cmd...>"
    exit 1
    ;;

  *)
    require_running
    as_dev "$@"
    ;;
esac
