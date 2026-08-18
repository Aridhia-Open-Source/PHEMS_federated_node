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

# charts/ is gitignored, so a fresh checkout has no subcharts and helm refuses to
# lint or render. Both targets below depend on this.
helm_deps:
	cd k8s/federated-node && helm dependency build || helm dependency update

helm_lint: helm_deps
	helm lint k8s/federated-node -f k8s/federated-node/dev.example.values.yml

# Renders with no cluster access - guards against a lookup that ArgoCD or CI cannot do.
helm_template: helm_deps
	helm template fn k8s/federated-node -f k8s/federated-node/dev.example.values.yml >/dev/null

show-db-passwords:
	@kubectl get secret -l federatednode.com/generated-password=true \
		-o go-template='{{range .items}}{{printf "%-26s" .metadata.name}}{{range $$k, $$v := .data}}{{$$k}}={{$$v | base64decode}}{{end}}{{"\n"}}{{end}}'

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

build_all_images:
	./scripts/build_all_images.sh $(word 2,$(MAKECMDGOALS))

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

uc1-seed:
	./dev.db/uc1_make_seed.sh

nuke:
	./scripts/nuke.sh

%:
	@: