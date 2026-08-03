#!/usr/bin/env bash

pkill -f "kubectl port-forward" || true

kubectl port-forward -n fn svc/fn-dev-dagster-webserver 3000:80 & \
kubectl port-forward -n fn svc/backend 5000:5000 & \
kubectl port-forward -n fn svc/db 5432:5432 & \
kubectl port-forward -n keycloak svc/keycloak 8080:80