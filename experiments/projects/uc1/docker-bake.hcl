# UC1's task image. Its source is the MVP-Code repo, which is not in this one: clone it into experiments/sources/uc1 first (see experiments/UC1_README.md). Without the clone, scripts/bake_files.sh leaves this file out.
# Bake runs from the repo root, so the context is relative to it. Used with the root docker-bake.hcl:
#   docker buildx bake -f docker-bake.hcl -f experiments/projects/uc1/docker-bake.hcl uc1-fn --push

variable "REGISTRY" {
  default = "localhost:5001"
}

variable "TAG" {
  default = "latest"
}

target "uc1-fn" {
  context = "experiments/sources/uc1"
  tags    = distinct(["${REGISTRY}/uc1-fn:latest", "${REGISTRY}/uc1-fn:${TAG}"])
}
