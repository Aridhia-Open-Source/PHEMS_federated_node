# 0029. Images are built with docker buildx bake

Status: Accepted, 2026-11-09.

## Context

Two shell scripts built the images: `scripts/build_all_images.sh` listed the directories and special-cased the names that clash (`nexus/api`, `nexus/ui`, the demo image), and `scripts/build_image.sh` built one. Experiments had their own build step in `fncli experiment build`, with the source directory and image name in `project.env`. The release's four images had their own Make targets with `docker build`. Adding an image meant editing a list in a script, and the tag and registry were repeated wherever an image was built.

## Decision

Images are `docker buildx bake` targets.

- **The root `docker-bake.hcl` holds the node's images.** The `default` group is what `make deploy` builds and pushes to the kind registry (dagster, alpine, kc-init, keycloak, nexus-api, nexus-ui and its dev stage). The `release` group is what a release publishes to `ghcr.io`, built without the local registry.
- **Each experiment brings its own `docker-bake.hcl`** with one target, `<name>-fn`, whose context is in its folder ([0028](0028-experiments-own-their-database-seed-image-and-dataset-file.md)). `scripts/bake_files.sh` finds them, so none is listed anywhere. It skips an experiment whose build context is missing (UC1 builds from a clone the repository does not hold). It also has a `targets` mode, because bake groups do not merge across files and `default` holds only the node's own images.
- **The make targets are the interface:**
  - `make images`: the `default` group and every experiment's target, pushed.
  - `make image NAME=<target>`: one target, pushed.
  - `make image-reload NAME=<target>`: push, then roll the deployments.
  - `make images-release TAG=<tag>`: the `release` group, loaded into the local docker, not pushed.
- **Tags:** one shared `DOCKER_TAG` (from `.dev.env`) plus `latest`. A target may pin its own tag in its bake file. A git SHA tag comes later.
- `scripts/build_all_images.sh` and `scripts/build_image.sh` are deleted.

## Consequences

- One definition per image, one place for the registry and the tag, and bake's parallel builds and cache.
- A new experiment image is a new file next to its source, not an edit to a script.
- `deploy.sh`, `reload_app.sh` and `fncli experiment build` call bake; `fncli experiment build NAME` builds one target.
- Tilt still builds the dev images with live update ([0020](0020-tilt-dev-loop.md)); bake builds what Tilt does not and what deploy and release need.
- The tag is still a shared string, not tied to the commit.

## Alternatives considered

- **Skaffold:** it overlaps Tilt, which already builds, pushes and live-updates the dev images ([0020](0020-tilt-dev-loop.md)), so there would be two build tools to keep in step.
- **A `build.sh` and `build.env` per project:** one more script and settings file per experiment, repeating the registry and tag.
- **Keep the two scripts and extend their list:** each new image is a script edit, and the name clashes stay special cases.
