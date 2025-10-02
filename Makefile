SHELL=/bin/bash
TAG := $(or $(TAG), 1.0)

hadolint:
	./scripts/run_hadolint.sh

run_local:
	./scripts/run_local.sh

dashboard:
	microk8s dashboard-proxy

pylint:
	./scripts/pylint.sh

chart:
	helm package k8s/federated-node -d artifacts/

helm_tests:
	docker build -f build/helm-unittest/Dockerfile . -t helm-unittest-fn
	docker run --name helm-test helm-unittest-fn
	docker rm helm-test

build_keycloak:
	docker build build/keycloak -f build/keycloak/keycloak.Dockerfile -t ghcr.io/aridhia-open-source/federated_keycloak:${TAG}

build_connector:
	docker build build/db-connector -t ghcr.io/aridhia-open-source/db_connector:${TAG}

build_alpine:
	docker build build/alpine -t ghcr.io/aridhia-open-source/alpine:${TAG}

build_kc_init:
	docker build build/kc-init -t ghcr.io/aridhia-open-source/keycloak_initializer:${TAG}
