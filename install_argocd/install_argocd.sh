#!/bin/bash

echo "Installing ArgoCD"
kubectl create namespace argocd

# Via Helm chart
helm repo add argo https://argoproj.github.io/argo-helm
kubectl apply -f argo-extra.yaml
helm install argocd argo/argo-cd -n argocd --create-namespace -f lookup-values.yaml

# Install CLI - Optional
echo "Installing ArgoCD CLI"
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
rm argocd-linux-amd64

# Add Repo from github
for repo in "https://github.com/Aridhia-Open-Source/PHEMS_federated_node" "https://github.com/Aridhia-Open-Source/federated-node-task-controller"
do
    argocd repo add "${repo}"
done

# Add app via k8s manifest
# kubectl apply -f fn_application.yaml
