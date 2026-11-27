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

# Where the release images go; CI passes ghcr.io/<owner>
variable "RELEASE_REGISTRY" {
  default = "ghcr.io/aridhia-open-source"
}

# Build cache for the release targets: CI sets "gha" on non-release builds; empty (the default) means no cache
variable "CACHE" {
  default = ""
}

function "cache_from" {
  params = [name]
  result = CACHE == "" ? [] : ["type=${CACHE},scope=${name}"]
}

function "cache_to" {
  params = [name]
  result = CACHE == "" ? [] : ["type=${CACHE},mode=max,scope=${name}"]
}

# One release image: RELEASE_REGISTRY/<name>:TAG
function "release_tags" {
  params = [name]
  result = ["${RELEASE_REGISTRY}/${name}:${TAG}"]
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

# What CI and the release publish (RELEASE_REGISTRY), built without REGISTRY
group "release" {
  targets = [
    "release-nexus-api",
    "release-keycloak",
    "release-alpine",
    "release-kc-init",
    "release-dagster",
    "release-nexus-operator",
  ]
}

target "dagster-fn" {
  context  = "dagster"
  contexts = { fednode = "nexus/fednode" }
  tags     = tags("dagster-fn")
}

# The Kopf operator (nexus/operator), with the shared fednode package like Dagster
target "nexus-operator-fn" {
  context  = "nexus/operator"
  contexts = { fednode = "nexus/fednode" }
  tags     = tags("nexus-operator-fn")
}

target "alpine-fn" {
  context  = "build/alpine"
  contexts = { fednode = "nexus/fednode" }
  tags     = tags("alpine-fn")
}

target "kc-init-fn" {
  context  = "build/kc-init"
  contexts = { fednode = "nexus/fednode" }
  tags     = tags("kc-init-fn")
}

target "keycloak-fn" {
  context = "build/keycloak"
  tags    = tags("keycloak-fn")
}

target "nexus-api-fn" {
  context  = "nexus/api"
  contexts = { fednode = "nexus/fednode" }
  tags     = tags("nexus-api-fn")
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

target "release-nexus-api" {
  inherits   = ["nexus-api-fn"]
  tags       = release_tags("nexus_api")
  cache-from = cache_from("nexus_api")
  cache-to   = cache_to("nexus_api")
}

target "release-keycloak" {
  inherits   = ["keycloak-fn"]
  tags       = release_tags("federated_keycloak")
  cache-from = cache_from("federated_keycloak")
  cache-to   = cache_to("federated_keycloak")
}

target "release-alpine" {
  inherits   = ["alpine-fn"]
  tags       = release_tags("alpine")
  cache-from = cache_from("alpine")
  cache-to   = cache_to("alpine")
}

target "release-kc-init" {
  inherits   = ["kc-init-fn"]
  tags       = release_tags("keycloak_initializer")
  cache-from = cache_from("keycloak_initializer")
  cache-to   = cache_to("keycloak_initializer")
}

target "release-dagster" {
  inherits   = ["dagster-fn"]
  tags       = release_tags("dagster_fn")
  cache-from = cache_from("dagster_fn")
  cache-to   = cache_to("dagster_fn")
}

target "release-nexus-operator" {
  inherits   = ["nexus-operator-fn"]
  tags       = release_tags("nexus_operator")
  cache-from = cache_from("nexus_operator")
  cache-to   = cache_to("nexus_operator")
}
