# Image builds on docker buildx bake

Status: done in #803 ("ci(security): security remediations"), on top of #798.

`docker-bake.hcl` is the one definition of every image's contexts and named contexts. CI, Tilt,
`mise run images` and `mise run images-release` all drive it.

## What changed

- **CI** (`.github/workflows/build.yml`): the six per-image jobs (three inline, one reusable
  `pipelines/build-docker.yml` call) are one `build-images` job running `docker/bake-action` over
  the `release` group. `init` outputs go in as bake variables: `TAG`, `RELEASE_REGISTRY`
  (`<DOCKER_CR>/<owner>`), `CACHE`.
- **Cache**: `CACHE=gha` (scoped per image) only off `main` and `dagster-main`; release-branch
  builds and local builds run with no cache. Test jobs' `mise-action` cache is off.
- **Bake file**: new `release-nexus-api` target; release tags come from `RELEASE_REGISTRY`
  (default `ghcr.io/aridhia-open-source`); `cache_from`/`cache_to` are empty unless `CACHE` is set.
- **Tilt**: the nexus-api, Dagster (and its run image) and operator custom builds run
  `docker buildx bake <target> --load`, setting only the tag and the optional `proxy_ca` secret.
  Deps, ignores and live_update syncs are unchanged. The UI dev image stays a `docker_build`
  (no named context).

## Not done

- The UI release image: not in the `release` group or the `promote` job yet; add both together.
- Tilt deps are still hand-listed, not read from `bake --print`.
