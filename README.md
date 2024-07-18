![phems_logo](https://github.com/aridhia/federated-node/assets/94359606/d95796b0-6fad-4dfb-b0c6-5b3e17ac4846)
## Federated Node service for PHEMS project
The development of the PHEMS ecosystem will entail the design and implementation of federated analytics, algorithms, governance framework and an implementation playbook.

# Deployment

See the [DEPLOYMENT](./DEPLOYMENT.md) document.

# Update
```sh
helm upgrade federatednode ./k8s/federated-node
```

# Run locally
Minikube or microk8s is required.
```sh
./scripts/run_local.sh minikube
# or
./scripts/run_local.sh micro
```

This will launch a Minikube cluster called `federatednode` (if using minikube), and apply the helm chart with the default `values.yaml`.

Open the nginx port with
```sh
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 443
```
Also add the custom host url to the hosts list
On Windows: `C:\WINDOWS\System32\drivers\etc\hosts`
On WSL/Linux: `/etc/hosts`
```
127.0.0.1 host-url
```
