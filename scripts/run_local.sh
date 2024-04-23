#!/bin/bash

set -e

LOCAL_CLUSTER=$1
if [[ "$LOCAL_CLUSTER" == "minikube" ]]; then
    export CLUSTER_NAME=federatednode
    echo "Starting MK"
    minikube start -p $CLUSTER_NAME --driver=docker
    echo "Switching context"
    kubectl config use-context $CLUSTER_NAME
else
    echo "Switching context"
    kubectl config use-context microk8s
fi

echo "applying definitions"

HELM_CHART_NAME=federatednode
INSTALLED_VERSION=$(helm list --filter "^$HELM_CHART_NAME" -o json | jq -r .[].chart)
CHART_VERSION=federated-node-$(grep 'version:' k8s/federated-node/Chart.yaml | sed 's/^.*: //')
DEV_VALUES="-f k8s/federated-node/values.yaml"

if [[ -f "k8s/federated-node/dev.values.yaml" ]]; then
    DEV_VALUES="$DEV_VALUES -f k8s/federated-node/dev.values.yaml"
fi

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
kubectl apply -f dev.k8s/deployments

echo "If new images are needed, load them up with:"
if [[ "$LOCAL_CLUSTER" == "minikube" ]]; then
    echo "minikube -p $CLUSTER_NAME image load <image_name>"
else
    echo "docker save <image_name> > fn.tar"
    echo "microk8s ctr image import fn.tar"
fi
NGINX_NAMESPACE=$(grep -oP '(?<=nginx:\s).*' k8s/federated-node/dev.values.yaml)

if [[ -z $NGINX_NAMESPACE ]]; then
    NGINX_NAMESPACE=$(grep -oP '(?<=nginx:\s).*' k8s/federated-node/values.yaml)
fi

echo "You can reach the FN on https://<host-url>"
kubectl port-forward -n "${NGINX_NAMESPACE}" svc/ingress-nginx-controller 443
