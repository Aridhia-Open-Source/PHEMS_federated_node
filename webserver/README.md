# FLASK APP
This folder holds the Flask app that serves the API backend for the Federated Node.

## Structure
Contains 2 folders:
- `app` holds the actual python code
- `build` holds files involved to build/serve the app through a Docker container
- `migrations` is an auto-generated folder from `alembic` which helps in keeping track of the database migrations, and offer a rollback functionality in case is needed.
- `tests` holds unit test files

## Dev Setup
```sh
sudo apt-get install -y python3.13 python3.13-venv python3.13-dev
uv init
source .venv/bin/activate
```

### uv
To upgrade dependencies, run:
```sh
uv lock --upgrade
```


### Tools
pylint should guarantee a minimum threshold of code quality/standards. It can be run with `make pylint`

### Run (dev mode)
```sh
make run
```

If you need to fetch the random generated secret for keycloak:
```sh
kubectl get secrets -n keycloak kc-secrets -o jsonpath='{.data}' | jq
```
#### Microk8s
If you are using microk8s, to send an image to the cluster:
```sh
docker tag ghcr.io/aridhia/federated_node_run:0.0.1-dev federated_node_run:0.0.1-dev
docker savefederated_node_run:0.0.1-dev > fndev.tar
microk8s ctr image import fndev.tar
```
#### minikube
If you are developing with minikube:
```sh
minikube load image ghcr.io/aridhia/federated_node_run:0.0.1-dev
#or
eval $(minikube docker-env)
make build_docker
```
Alternatively, minikube has a variety of method to achieve this. See https://minikube.sigs.k8s.io/docs/handbook/pushing/


### Tests (dev mode)
```sh
make run_tests
# that will still run a set of tests, but will keep
# keycloak, and DB running so further tests can be run locally
python -m unittest
```
