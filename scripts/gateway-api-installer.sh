#!/bin/bash

VERSION=${1:-"1.4.0"}

echo "Installing Gateway API version $VERSION"

kubectl apply --server-side -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/v${VERSION}/standard-install.yaml"
