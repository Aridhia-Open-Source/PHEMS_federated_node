SHELL=/bin/bash

hadolint:
	./scripts/run_hadolint.sh

run_local:
	./scripts/run_local.sh

expose_api:
	minikube -p federatednode service backend --url

dashboard:
	minikube -p federatednode dashboard --url --port 41234

pylint:
	./scripts/pylint.sh

chart:
	helm package k8s/federated-node -d artifacts/
