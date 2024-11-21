# ArgoCD Installation

We do reccommend to install ArgoCD before installing the federated node to keep up-to-date with little effort.

The installation needs to be performed with some configuration tweaks, this is why the folder [install_argocd](./install_argocd/) exists.

Within, the [install_argocd.sh](./install_argocd/install_argocd.sh) was created to automate the whole process.

```sh
./install_argocd/install_argocd.sh
```

### What does the installation script does
- Create the `argocd` namespace
- Add the helm repo locally
- Install argo in the cluster via the helm chart
- Add the Federated Node repository to ArgoCD

### Install The Federated Node
It can be done via CLI:
```sh
kubectl apply -f ./install_argocd/fn_application.yaml
```
In this case make sure the values file exists in the install_argocd folder or to paste the contents in the `spec.source.helm.values` section. Follow the comments and delete the values sections that are not used.

Or via the UI, which is straightfotward.
