#!/usr/bin/env bash

# A rerun replaces an earlier run (from any worktree: the ports are the machine's). Stop its restart
# loops first, through its pid file, then the forwards themselves below.
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/fn-portfwd.pid"
if [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2> /dev/null; then
  while kill -0 "$(cat "$PIDFILE")" 2> /dev/null; do sleep 0.1; done
fi
echo $$ > "$PIDFILE"

# pkill only signals; it does not wait. Without draining first, the forwards below
# race the dying ones for their sockets and lose with "address already in use".
pkill -f "kubectl port-forward" || true

for _ in $(seq 50); do
  pgrep -f "kubectl port-forward" > /dev/null || break
  sleep 0.1
done

if pgrep -f "kubectl port-forward" > /dev/null; then
  echo "port-forwards did not exit after SIGTERM, forcing" >&2
  pkill -9 -f "kubectl port-forward" || true
  sleep 0.5
fi

# A forward ends when its pod goes (an upgrade, a Flux reconcile): start it again on the new pod
forward() {
  while true; do
    kubectl port-forward "$@"
    sleep 2
  done
}

# Stopping this script stops its loops, then the forwards they started
stop() {
  trap - INT TERM EXIT
  kill $(jobs -p) 2> /dev/null
  pkill -f "kubectl port-forward"
  exit 0
}
trap stop INT TERM EXIT

forward -n fn svc/fn-dev-dagster-webserver 3000:80 &
forward -n fn svc/nexus-api 5000:5000 &
forward -n fn svc/nexus-ui 8088:80 &
forward -n fn svc/db 5432:5432 &
forward -n fn svc/gitea 4000:4000 &
forward -n keycloak svc/keycloak 8080:80 &
wait
