SHELL=/bin/bash
TAG := $(or $(TAG), 1.0)

# SANDBOX=1 make <targets> runs the whole command line once inside the dev sandbox
# (scripts/sandbox.sh), e.g. SANDBOX=1 make cluster up, SANDBOX=1 make deploy.
ifeq ($(SANDBOX),1)

$(or $(firstword $(MAKECMDGOALS)),sandbox-default):
	@./scripts/sandbox.sh make $(MAKECMDGOALS) $(filter-out SANDBOX=%,$(MAKEOVERRIDES))

%:
	@:

else

hadolint:
	./scripts/run_hadolint.sh

run_local:
	./scripts/run_local.sh

dashboard:
	microk8s dashboard-proxy

pylint:
	./scripts/pylint.sh

pylint_dagster:
	PROJECT=dagster ./scripts/pylint.sh

tests_dagster:
	cd dagster && ./run_tests.sh ci

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

# Corporate MITM proxy simulation (see scripts/proxy-sim.sh). A fake hospital laptop behind a
# TLS-intercepting proxy. Walk through in order:
# up -> pull (fails, no route) -> proxy -> pull (fails, x509) -> trust -> pull (works) -> flow -> down.
# DIRECT=1 make proxy-sim-up    control run: normal internet, no proxy
# make proxy-sim-flow           the first-time steps; resume with FROM=N
# make proxy-sim-pull IMAGE=ghcr.io/org/name:tag
proxy-sim-build:
	./scripts/proxy-sim.sh build

proxy-sim-up:
	./scripts/proxy-sim.sh up

proxy-sim-proxy:
	./scripts/proxy-sim.sh proxy

proxy-sim-trust:
	./scripts/proxy-sim.sh trust

proxy-sim-pull:
	./scripts/proxy-sim.sh pull $(IMAGE)

proxy-sim-flow:
	./scripts/proxy-sim.sh flow $(if $(FROM),--from $(FROM))

proxy-sim-shell:
	./scripts/proxy-sim.sh shell

proxy-sim-down:
	./scripts/proxy-sim.sh down

deploy-owner:
	./scripts/deploy_owner.sh show

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

# Real experiments against the node, see experiments/README.md
# make experiments up | down | seed uc1 | build uc1 | run uc1 | run-local uc1
.PHONY: experiments
experiments:
	@./experiments/experiments.sh $(filter-out $@,$(MAKECMDGOALS))

# One-step dev install for a fresh clone (Debian 13 / Ubuntu 24.04+, Docker required)
dev-install:
	./scripts/install-dev.sh

# Throwaway Debian laptop in Docker for testing the installer, see scripts/sandbox.sh
# make sandbox up | down | shell; ./scripts/sandbox.sh <cmd> for anything else
sandbox:
	@./scripts/sandbox.sh $(filter-out $@,$(MAKECMDGOALS))

nuke:
	./scripts/nuke.sh

%:
	@:

endif
