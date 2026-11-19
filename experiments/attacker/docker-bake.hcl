# The attacker experiment's task image: a hostile task that tries to break out of its isolation.
# Bake runs from the repo root, so the context is relative to it. Used with the root docker-bake.hcl:
#   docker buildx bake -f docker-bake.hcl -f experiments/attacker/docker-bake.hcl attacker-fn --push

variable "REGISTRY" {
  default = "localhost:5001"
}

variable "TAG" {
  default = "latest"
}

target "attacker-fn" {
  context = "experiments/attacker/image"
  tags    = distinct(["${REGISTRY}/attacker-fn:latest", "${REGISTRY}/attacker-fn:${TAG}"])
}
