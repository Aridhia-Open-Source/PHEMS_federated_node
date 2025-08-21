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

build_keycloak:
	docker build build/keycloak -f build/keycloak/keycloak.Dockerfile -t ghcr.io/aridhia-open-source/federated_keycloak:0.0.1

build_connector:
	docker build build/db-connector -t ghcr.io/aridhia-open-source/db_connector:0.0.1

build_alpine:
	docker build build/alpine -t ghcr.io/aridhia-open-source/alpine:0.0.1

build_kc_init:
	docker build build/kc-init -t ghcr.io/aridhia-open-source/keycloak_initializer:0.0.1
