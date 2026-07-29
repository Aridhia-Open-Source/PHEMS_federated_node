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

build_dagster:
	docker build dagster -t ghcr.io/aridhia-open-source/dagster_fn:${TAG}

pip_compile:
	./scripts/pip_compile.sh $(filter-out $@,$(MAKECMDGOALS))

build_reload:
	./scripts/build_image.sh $(word 2,$(MAKECMDGOALS)) $(word 3,$(MAKECMDGOALS)) && kubectl rollout restart deployment

build_image:
	./scripts/build_image.sh $(word 2,$(MAKECMDGOALS)) $(word 3,$(MAKECMDGOALS))

reload_app:
	./scripts/reload_app.sh

cluster:
	@./scripts/cluster.sh $(filter-out $@,$(MAKECMDGOALS))

up down:
	@:

deploy:
	./scripts/deploy.sh

teardown:
	./scripts/teardown.sh

portfwd:
	./scripts/portfwd.sh

upgrade:
	./scripts/upgrade.sh

tilt-up:
	tilt up

tilt-down:
	tilt down

tilt-logs:
	tilt logs

tilt-open:
	tilt open

nuke:
	./scripts/nuke.sh

%:
	@: