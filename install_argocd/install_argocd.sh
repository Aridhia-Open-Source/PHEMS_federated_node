#!/bin/bash

this=$(basename "$0")

show_help() {
    echo "$this [-u username] [-t token]"
}
while getopts "h?u:t:" opt; do
  case "$opt" in
    h|\?)
      show_help
      exit 0
      ;;
    u) username="$OPTARG"
      ;;
    t) password="$OPTARG"
      ;;
  esac
done

if [[ -z "$username" || -z "$password" ]]; then
    echo "Missing credentials. Run $this -h to check how to provide these options"
    exit 1
fi
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
for repo in "https://github.com/Aridhia-Open-Source/federated_node" "https://github.com/Aridhia-Open-Source/go-controller"
do
    argocd repo add "${repo}" --username "${username}" --password "${password}"
done

# Add app via k8s manifest
# kubectl apply -f fn_application.yaml
