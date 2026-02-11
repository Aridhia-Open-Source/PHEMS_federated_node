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
	./scripts/run_helm_tests.sh

build_keycloak:
	docker build build/keycloak -t ghcr.io/aridhia-open-source/federated_keycloak:${TAG}

build_connector:
	docker build build/db-connector -t ghcr.io/aridhia-open-source/db_connector:${TAG}

build_alpine:
	docker build build/alpine -t ghcr.io/aridhia-open-source/alpine:${TAG}

build_kc_init:
	docker build build/kc-init -t ghcr.io/aridhia-open-source/keycloak_initializer:${TAG}

compile:
	./scripts/compile.sh $(filter-out $@,$(MAKECMDGOALS))

build_image:
	./scripts/build_image.sh $(word 2,$(MAKECMDGOALS)) $(word 3,$(MAKECMDGOALS))

deploy:
	./scripts/deploy.sh

portfwd:
	./scripts/portfwd.sh

upgrade:
	./scripts/upgrade.sh

run_job:
	./scripts/run_job.sh

%:
	@: