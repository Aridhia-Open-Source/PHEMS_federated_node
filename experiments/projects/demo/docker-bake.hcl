# The demo experiment's task image.
# Bake runs from the repo root, so the context is relative to it. Used with the root docker-bake.hcl:
#   docker buildx bake -f docker-bake.hcl -f experiments/projects/demo/docker-bake.hcl demo-fn --push

variable "REGISTRY" {
  default = "localhost:5001"
}

variable "TAG" {
  default = "latest"
}

target "demo-fn" {
  context = "experiments/projects/demo/image"
  tags    = distinct(["${REGISTRY}/demo-fn:latest", "${REGISTRY}/demo-fn:${TAG}"])
}
