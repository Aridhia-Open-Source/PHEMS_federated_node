#!/bin/bash

VERSION=${1:-"1.4.0"}

echo "Installing Gateway API version $VERSION"

kubectl apply --server-side -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/v${VERSION}/experimental-install.yaml"

echo "Installing Traefik CRDs"
kubectl apply --server-side -f "https://raw.githubusercontent.com/traefik/traefik/v3.6/docs/content/reference/dynamic-configuration/kubernetes-crd-definition-v1.yml"
