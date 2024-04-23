# FLASK APP
This folder holds the Flask app that serves the API backend for the Federated Node.

## Structure
Contains 2 folders:
- `app` holds the actual python code and the `Pipfile`s for setting up environment and dependencies
- `build` holds files involved to build/serve the app through a Docker container
- `migrations` is an auto-generated folder from `alembic` which helps in keeping track of the database migrations, and offer a rollback functionality in case is needed.
- `tests` holds unit test files

## Dev Setup
```sh
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
python3.12 -m venv .venv
source .venv/bin/activate
pip install pipenv
```

### pipenv
The first use packages need to be installed:
`pipenv install --categories 'packages local-dev'`

then you can either run a single command -> `pipenv run ...`

or spawn a new console with the virtualenv -> `pipenv shell`

Check for dependencies upgrades -> `pipenv update --dry-run`

Check for dependencies vulnerabilities locally -> `pipenv check`

Add new package -> `pipenv install --categories <packages|local-dev|tests> package`

If pipenv returns a lock version error, run `pipenv update` (doesn't actively update dependencies versions) to bring [Pipfile.lock](./Pipfile.lock) on par with [Pipfile](./Pipfile)

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
# Once the container bash is available
python -m unittest
```
