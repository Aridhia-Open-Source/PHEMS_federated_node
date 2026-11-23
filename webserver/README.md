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
python3.13 -m venv .venv
source .venv/bin/activate
```

### Tools
pylint should guarantee a minimum threshold of code quality/standards. It is run from the
repository root with `make pylint` (the target lives in the top-level `Makefile`).

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
Run these from the `webserver` folder. They all need Docker.

```sh
make tests_local        # the unit tests, while you're working on the code
make tests_ci           # the same unit tests, the way CI runs them
make tests_integration  # kc-init against a real Keycloak
```

`make tests_local` builds the test image and runs the unit tests with pytest against a Postgres container. Your local `app` and `tests` folders are mounted in, so changes are picked up without a rebuild. The database is left running afterwards, so the next run is quicker. `make run_tests` is the old name for this and does the same thing.

`make tests_ci` runs the same unit tests from the image as built, with nothing mounted. It prints the app logs if anything fails, then removes the containers and the data volume. Use it to check a change the way the CI pipeline will see it before you push.

`make tests_integration` starts a real Keycloak and Postgres and runs kc-init, the job that sets up the Keycloak realm, several times against the same database. This catches problems that only show up on a second run or an upgrade, which the unit tests can't. Run it when you change kc-init, the realm settings or the Keycloak setup. It cleans up after itself.

`tests_local` and `tests_ci` both copy a coverage report to `../artifacts/coverage.xml`.
