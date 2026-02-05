#!/usr/bin/env bash

pkill -f "kubectl port-forward" || true

kubectl port-forward svc/fn-dev-dagster-webserver 3000:80 & \
kubectl port-forward svc/backend 5000:5000 & \
kubectl port-forward svc/db 5432:5432 & \
