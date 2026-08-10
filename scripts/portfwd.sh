#!/usr/bin/env bash

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

kubectl port-forward -n fn svc/fn-dev-dagster-webserver 3000:80 & \
kubectl port-forward -n fn svc/backend 5000:5000 & \
kubectl port-forward -n fn svc/db 5432:5432 & \
kubectl port-forward -n fn svc/db-datasets 5433:5432 & \
kubectl port-forward -n keycloak svc/keycloak 8080:80
