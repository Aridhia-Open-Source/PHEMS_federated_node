SHELL=/bin/bash
TAG := $(or $(TAG), 1.0)

.DEFAULT_GOAL := help

# Lists every target that has a `## description` after its name
.PHONY: help init-conf cluster-up cluster-down pip-compile
help: ## List the targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-18s %s\n", $$1, $$2}'

init-conf: ## Create .dev.env and dev.values.yaml from the examples, ask for the first Keycloak user
	./scripts/init_conf.sh

hadolint: ## Lint the Dockerfiles
	./scripts/run_hadolint.sh

pylint: ## Lint nexus-api
	./scripts/pylint.sh

pylint_dagster: ## Lint Dagster
	PROJECT=dagster ./scripts/pylint.sh

tests_dagster: ## Run the Dagster tests the way CI does
	cd dagster && ./run_tests.sh ci

helm_tests: ## Run the chart's helm unit tests
	./scripts/run_helm_tests.sh

# charts/ is gitignored, so a fresh checkout has no subcharts and helm refuses to
# lint or render. Both targets below depend on this.
helm_deps: ## Build the chart's subcharts
	cd k8s/federated-node && helm dependency build || helm dependency update

helm_lint: helm_deps ## Lint the chart
	helm lint k8s/federated-node -f k8s/federated-node/dev.example.values.yml

# Renders with no cluster access - guards against a lookup that ArgoCD or CI cannot do.
helm_template: helm_deps ## Render the chart with no cluster
	helm template fn k8s/federated-node -f k8s/federated-node/dev.example.values.yml >/dev/null

show-db-passwords: ## Print the generated database passwords
	@kubectl get secret -l federatednode.com/generated-password=true \
		-o go-template='{{range .items}}{{printf "%-26s" .metadata.name}}{{range $$k, $$v := .data}}{{$$k}}={{$$v | base64decode}}{{end}}{{"\n"}}{{end}}'

# make pip-compile DIR=nexus/api [OUT=requirements-dev.txt] [ARGS="--upgrade"]
# DIR also exists in some environments, so only the command line counts
PIP_DIR = $(if $(filter command line,$(origin DIR)),$(DIR),$(error usage: make $@ DIR=<component dir> [OUT=<file>] [ARGS=<pip-compile flags>]))

pip-compile: ## Lock a component's requirements: DIR=nexus/api [OUT=file] [ARGS=flags]
	./scripts/pip_compile.sh $(PIP_DIR) $(OUT) $(ARGS)

# Images are docker buildx bake targets, see docker-bake.hcl. Dev images are tagged latest and pushed to localhost:5001.
# make images | image NAME=nexus-api-fn | image-reload NAME=nexus-api-fn | images-release TAG=1.2.3
# NAME also exists in some shells' environments (the host name), so only the command line counts
IMAGE_NAME = $(if $(filter command line,$(origin NAME)),$(NAME),$(error usage: make $@ NAME=<bake target>))

.PHONY: images image image-reload images-release
images: ## Build and push every image to localhost:5001
	scripts/build_images.sh

image: ## Build and push one image: NAME=nexus-api-fn
	scripts/build_images.sh $(IMAGE_NAME)

image-reload: ## Build and push one image, then restart the deployments: NAME=nexus-api-fn
	scripts/build_images.sh $(IMAGE_NAME) && kubectl rollout restart deployment

# The ghcr.io images the release publishes, tagged TAG and loaded into the local docker, not pushed
images-release: ## Build the release images into the local docker: TAG=1.2.3
	TAG=$(TAG) docker buildx bake -f docker-bake.hcl release --load

reload_app: ## Rebuild the Dagster and nexus-api images and restart their pods
	./scripts/reload_app.sh

cluster-up: ## Start the kind cluster and the local registries
	@./scripts/cluster.sh up

# make cluster-down ARGS=--remove-registries  also deletes the registries
cluster-down: ## Delete the kind cluster, keep the registries
	@./scripts/cluster.sh down $(ARGS)

deploy: ## Build images, install or upgrade the Helm release, restart the app pods
	./scripts/deploy.sh

teardown: ## Remove the deployment and its persistent data
	./scripts/teardown.sh

portfwd: ## Port-forward the node's services (when Tilt is not running)
	./scripts/portfwd.sh

deploy-owner: ## Show which worktree owns the dev cluster
	./scripts/deploy_owner.sh show

# New sibling worktree with the gitignored dev config copied in
# make worktree NAME=wt-foo BRANCH=feature/foo [BASE=main]
.PHONY: worktree
worktree: ## New sibling worktree with the dev config: NAME=dir BRANCH=branch [BASE=ref]
	@test "$(origin NAME)" = "command line" -a "$(origin BRANCH)" = "command line" -a -n "$(NAME)" -a -n "$(BRANCH)" || { echo "usage: make worktree NAME=<dir> BRANCH=<branch> [BASE=<ref>]" >&2; exit 1; }
	@./scripts/new-worktree.sh "$(NAME)" "$(BRANCH)" $(if $(filter command line,$(origin BASE)),"$(BASE)")
