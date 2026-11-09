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

pip_compile:
	./scripts/pip_compile.sh $(filter-out $@,$(MAKECMDGOALS))

# Images are docker buildx bake targets, see docker-bake.hcl. Tag and registry come from .dev.env's DOCKER_TAG and localhost:5001.
# make images | image NAME=nexus-api-fn | image-reload NAME=nexus-api-fn | images-release TAG=1.2.3
BAKE = source .dev.env && TAG=$$DOCKER_TAG docker buildx bake -f docker-bake.hcl $$(scripts/bake_files.sh)
# NAME also exists in some shells' environments (the host name), so only the command line counts
IMAGE_NAME = $(if $(filter command line,$(origin NAME)),$(NAME),$(error usage: make $@ NAME=<bake target>))

.PHONY: images image image-reload images-release
images:
	$(BAKE) default $$(scripts/bake_files.sh targets) --push

image:
	$(BAKE) $(IMAGE_NAME) --push

image-reload:
	$(BAKE) $(IMAGE_NAME) --push && kubectl rollout restart deployment

# The ghcr.io images the release publishes, tagged TAG and loaded into the local docker, not pushed
images-release:
	TAG=$(TAG) docker buildx bake -f docker-bake.hcl release --load

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

deploy-owner:
	./scripts/deploy_owner.sh show

# New sibling worktree with the gitignored dev config copied in
# make worktree NAME=wt-foo BRANCH=feature/foo [BASE=main]
.PHONY: worktree
worktree:
	@test "$(origin NAME)" = "command line" -a "$(origin BRANCH)" = "command line" -a -n "$(NAME)" -a -n "$(BRANCH)" || { echo "usage: make worktree NAME=<dir> BRANCH=<branch> [BASE=<ref>]" >&2; exit 1; }
	@./scripts/new-worktree.sh "$(NAME)" "$(BRANCH)" $(if $(filter command line,$(origin BASE)),"$(BASE)")

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
# make experiments up | build uc1 | seed uc1 | setup uc1 | run uc1 | teardown uc1 | down  (run --local: call fncli directly)
.PHONY: experiments
experiments:
	@fncli experiment $(filter-out $@,$(MAKECMDGOALS))

nuke:
	./scripts/nuke.sh

%:
	@: