#!/bin/bash

if [[ -z "$VERSION" ]]; then
  echo "Missing VERSION env var. Please specify a CRD version to install"
  exit 1
fi

kubectl apply --server-side -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/v${VERSION}/standard-install.yaml"
