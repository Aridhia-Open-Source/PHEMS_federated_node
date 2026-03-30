# Local Kubernetes Cluster

[kind](https://kind.sigs.k8s.io/) is a tool for running local Kubernetes clusters using Docker container "nodes".
kind was primarily designed for testing Kubernetes itself, but may be used for local development or CI.

To get setup with kind, follow the official [quick-start](https://kind.sigs.k8s.io/docs/user/quick-start/) guide.

## Setup
```bash
# Install kind
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# Verify kind
kind version

# Install helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Verify helm
helm version
```

## Commands
```bash
# Create cluster
kind create cluster --config kind-config.yaml -n fn

# Verify cluster
kubectl cluster-info
kubectl get nodes

# Delete cluster
kind delete cluster
```

## References
- Ingress:
  http://*.localhost:8080



