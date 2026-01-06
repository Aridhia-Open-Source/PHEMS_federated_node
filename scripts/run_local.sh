#!/bin/bash

set -e

DEV_VALUES=${1:-"-f k8s/federated-node/dev.values.yaml"}
HELM_CHART_NAME=federatednode
INSTALLED_VERSION=$(helm list --filter "^$HELM_CHART_NAME" -o json | jq -r .[].chart)
CHART_VERSION=federated-node-$(grep 'version:' k8s/federated-node/Chart.yaml | sed 's/^.*: //')

if [[ ! microk8s ]]; then
    echo "Micork8s is not installed"
    exit 1
fi

echo "If getting context errors:"
echo
echo "mv ~/.kube/config > ~/.kube/config.backup"
echo "yq eval-all '. as $item ireduce ({}; . * $item)' microconfig.yaml ~/.kube/config > ~/.kube/config"
echo


if [[ ! jq ]]; then
    echo "jq is not installed"
    echo "apt-get install jq"
    echo "or"
    echo "sudo apt-get install jq"
    exit 1
fi

kubectl config use-context microk8s

echo "applying definitions"

pushd k8s/federated-node
    helm dependency update
    helm dependency build
popd

if [[ -z "$INSTALLED_VERSION" ]]; then
    echo "Applying helm chart"
    helm install $HELM_CHART_NAME k8s/federated-node $DEV_VALUES
else
    if [[ $INSTALLED_VERSION = "$CHART_VERSION" ]]; then
        echo "Current version is the latest!"
    else
        echo "Upgrading installed helm chart"
        helm upgrade $HELM_CHART_NAME k8s/federated-node $DEV_VALUES
    fi
fi

echo "Creating a separate test db"
kubectl apply -f dev.k8s/deployments/db.yaml

echo "If new images are needed, load them up with:"
echo "docker save <image_name> > fn.tar"
echo "microk8s ctr image import fn.tar"

NGINX_NAMESPACE=$(grep -oP '(?<=nginx:\s).*' k8s/federated-node/dev.values.yaml)

if [[ -z $NGINX_NAMESPACE ]]; then
    NGINX_NAMESPACE=$(grep -oP '(?<=nginx:\s).*' k8s/federated-node/values.yaml)
fi

echo "You can reach the FN on https://<host-url>"
kubectl port-forward -n "${NGINX_NAMESPACE}" svc/ingress-nginx-controller 443
