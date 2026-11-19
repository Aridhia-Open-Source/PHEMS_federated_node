# Every image the node builds. Run from the repo root:
#   scripts/build_images.sh [TARGET...]
# or use `mise run images`, `mise run image --target <target>`, `mise run images-release --tag x`.
# Each experiment brings its own file, experiments/NAME/docker-bake.hcl.

variable "REGISTRY" {
  default = "localhost:5001"
}

# Dev builds use latest; releases pass TAG (mise run images-release --tag x). Tilt tags by content hash instead.
variable "TAG" {
  default = "latest"
}

# Where the release targets push: ghcr.io, or another registry (the kind registry in dev)
# (RELEASE_REGISTRY=kind-registry:5000).
variable "RELEASE_REGISTRY" {
  default = "ghcr.io/aridhia-open-source"
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
    "nexus-operator-fn",
  ]
}

# What the release publishes to RELEASE_REGISTRY, built without REGISTRY
group "release" {
  targets = [
    "release-keycloak",
    "release-alpine",
    "release-kc-init",
    "release-dagster",
    "release-nexus-api",
    "release-nexus-ui",
    "release-nexus-operator",
  ]
}

target "dagster-fn" {
  context  = "dagster"
  contexts = { nexus-client = "nexus/client" }
  tags     = tags("dagster-fn")
}

# The Kopf operator (nexus/operator), with the shared nexus-api client like Dagster
target "nexus-operator-fn" {
  context  = "nexus/operator"
  contexts = { nexus-client = "nexus/client" }
  tags     = tags("nexus-operator-fn")
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
  tags     = ["${RELEASE_REGISTRY}/federated_keycloak:${TAG}"]
}

target "release-alpine" {
  inherits = ["alpine-fn"]
  tags     = ["${RELEASE_REGISTRY}/alpine:${TAG}"]
}

target "release-kc-init" {
  inherits = ["kc-init-fn"]
  tags     = ["${RELEASE_REGISTRY}/keycloak_initializer:${TAG}"]
}

target "release-dagster" {
  inherits = ["dagster-fn"]
  tags     = ["${RELEASE_REGISTRY}/dagster_fn:${TAG}"]
}

target "release-nexus-api" {
  inherits = ["nexus-api-fn"]
  tags     = ["${RELEASE_REGISTRY}/nexus_api:${TAG}"]
}

target "release-nexus-ui" {
  inherits = ["nexus-ui-fn"]
  tags     = ["${RELEASE_REGISTRY}/federated_node_nexus_ui:${TAG}"]
}

target "release-nexus-operator" {
  inherits = ["nexus-operator-fn"]
  tags     = ["${RELEASE_REGISTRY}/nexus_operator:${TAG}"]
}
