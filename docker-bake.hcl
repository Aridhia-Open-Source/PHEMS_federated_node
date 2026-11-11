# Every image the node builds. Run from the repo root:
#   docker buildx bake -f docker-bake.hcl $(scripts/bake_files.sh) [TARGET...] --push
# or use `make images`, `make image NAME=<target>`, `make images-release TAG=x`.
# Each experiment brings its own file, experiments/NAME/docker-bake.hcl.

variable "REGISTRY" {
  default = "localhost:5001"
}

# Dev builds use latest; releases pass TAG (make images-release TAG=x). Tilt tags by content hash instead.
variable "TAG" {
  default = "latest"
}

# <registry>/<name>:latest and :TAG, once if TAG is latest
function "tags" {
  params = [name]
  result = distinct(["${REGISTRY}/${name}:latest", "${REGISTRY}/${name}:${TAG}"])
}

# The images deploy.sh builds and pushes to the kind registry
group "default" {
  targets = [
    "dagster-fn",
    "alpine-fn",
    "kc-init-fn",
    "keycloak-fn",
    "nexus-api-fn",
    "nexus-ui-fn",
    "nexus-ui-dev-fn",
  ]
}

# What the release publishes to ghcr.io, built without REGISTRY
group "release" {
  targets = [
    "release-keycloak",
    "release-alpine",
    "release-kc-init",
    "release-dagster",
  ]
}

target "dagster-fn" {
  context = "dagster"
  tags    = tags("dagster-fn")
}

target "alpine-fn" {
  context = "build/alpine"
  tags    = tags("alpine-fn")
}

target "kc-init-fn" {
  context = "build/kc-init"
  tags    = tags("kc-init-fn")
}

target "keycloak-fn" {
  context = "build/keycloak"
  tags    = tags("keycloak-fn")
}

target "nexus-api-fn" {
  context = "nexus/api"
  tags    = tags("nexus-api-fn")
}

target "nexus-ui-fn" {
  context = "nexus/ui"
  tags    = tags("nexus-ui-fn")
}

# The Vite dev server stage, which Tilt and the chart's nexus.ui.devServer use
target "nexus-ui-dev-fn" {
  context = "nexus/ui"
  target  = "dev"
  tags    = tags("nexus-ui-dev-fn")
}

target "release-keycloak" {
  inherits = ["keycloak-fn"]
  tags     = ["ghcr.io/aridhia-open-source/federated_keycloak:${TAG}"]
}

target "release-alpine" {
  inherits = ["alpine-fn"]
  tags     = ["ghcr.io/aridhia-open-source/alpine:${TAG}"]
}

target "release-kc-init" {
  inherits = ["kc-init-fn"]
  tags     = ["ghcr.io/aridhia-open-source/keycloak_initializer:${TAG}"]
}

target "release-dagster" {
  inherits = ["dagster-fn"]
  tags     = ["ghcr.io/aridhia-open-source/dagster_fn:${TAG}"]
}
