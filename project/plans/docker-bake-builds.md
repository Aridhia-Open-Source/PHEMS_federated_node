# Plan: one image build definition — docker buildx bake everywhere

Status: plan only, no implementation. Spawned from #798's CI findings and #786's gap.

## Context

Three image-build mechanisms drift apart today:

- **CI** (`.github/workflows/build.yml`) calls the shared `pipelines/build-docker.yml` reusable
  workflow for simple images, but three jobs (`build-dagster-image`, `build-alpine-image`,
  `build-kc-init-image`) inline the same five docker actions because those images need a
  *named build context* (`nexus-client=nexus/client`, `fednode=nexus/fednode`) that the
  reusable workflow cannot accept. This produced #798's failures: 15 unpinned `uses:` refs
  (pinact), plus most of the zizmor findings (credential persistence, unpinned uses,
  template injection in the inline steps).
- **`docker-bake.hcl`** already declares every image — contexts, named contexts, tags — and
  dev image builds (`mise run images` → `scripts/build_images.sh`) already use it. It even
  has `nexus-ui-fn` and `nexus-ui-dev-fn` targets: the UI image gap fixed by #786 would
  have been impossible if CI drove bake, because adding a target there automatically puts
  it in the build.
- **Tilt** uses `docker_build`/`docker_build_with_restart` for simple images and a
  hand-written `docker buildx build --build-context ...` custom build for dagster
  (`Tiltfile:112-114`), because `docker_build` has no named-context support (confirmed in
  the Tilt API: no `extra_build_contexts` parameter).

Decision: `docker-bake.hcl` becomes the single definition of every image's context(s),
secrets and cache; CI and Tilt both drive `docker buildx bake`.

## Work items

### 1. Extend `docker-bake.hcl` for CI and Tilt use

- Add `secret` attributes to targets that need the pip-index proxy secret (today appended
  as raw flags by Tilt's `BUILD_SECRET` and CI's inline jobs).
- Add `cache-from`/`cache-to type=gha` attributes (behind a variable so local builds skip
  them) to replace the inline jobs' GitHub Actions cache.
- Parameterize tags/registry as bake variables so CI's `init` job outputs can be passed as
  `--set` overrides; keep `tags()` defaulting to `localhost:5001` for dev.
- Verify the UI targets build the release variant #786 added (`nexus/ui` Dockerfile's
  nginx stage) and the dev variant (Tilt's `target='dev'`).

### 2. CI: replace per-image jobs with bake

- Replace the reusable-workflow calls and the three inline jobs with: checkout,
  setup-buildx (hash-pinned), one `docker buildx bake` invocation over the release target
  group, tags/registry set from `init` outputs.
- Keep the `promote` job as-is: it is `buildx imagetools create` retagging, not a build.
- Re-run pinact (whole file) — the inline sections it flagged are deleted.
- Re-check zizmor: inline docker steps disappear, removing the unpinned-uses, most
  credential-persistence, and the template-injection findings at build.yml:615-616/648/650.
- Keep #786's `build-nexus-ui-image` coverage by including `nexus-ui-fn` in the release
  group; delete its hand-written job in the same change.

### 3. Tilt: `bake_build_with_restart` helper

```python
def bake_build_with_restart(ref, target, live_update=[], entrypoint=[], ignore=[], extra_deps=[]):
  meta = decode_json(local('docker buildx bake {} --print'.format(target)))['target'][target]
  deps = [meta['context'], meta.get('dockerfile', 'Dockerfile')]
  deps += [p for p in meta.get('contexts', {}).values()]  # named contexts auto-watched
  deps += extra_deps
  custom_build_with_restart(
    ref,
    'docker buildx bake {t} --load --set {t}.tags=$EXPECTED_REF'.format(t=target),
    deps=deps, ignore=ignore + ['**/__pycache__', '**/*.pyc'],
    entrypoint=entrypoint, live_update=live_update,
  )
```

- Convert the dagster custom build, the nexus-api `docker_build_with_restart` and the
  nexus-ui-dev `docker_build` to it (bake targets already exist for all three).
- `watch_file('docker-bake.hcl')` so editing the bake file re-reads `--print` output.
- Map `BUILD_SECRET` onto bake `secret` attributes.

### 4. Validate

- `mise run images` unchanged (already bake) — confirm targets still build after the
  hcl edits.
- `tilt up`: live reload works for all three converted images (sync + restart wrapper).
- CI on the PR: pinact and zizmor findings for build.yml drop to zero; image tags match
  the current per-job outputs; promote/release flow unchanged on a dry run.

## Trade-offs accepted

- Tilt `deps` become whole-context watches (from `bake --print`) instead of curated
  `only=` lists: slightly more rebuild triggers, but they can never go stale.
- `local('bake --print')` runs at Tiltfile load; mitigated by `watch_file`.
- The reusable `pipelines/build-docker.yml` workflow stops being used by this repo
  (other repos may still use it; no change needed there).

## Out of scope

- The `promote` retagging job (`imagetools create`).
- zizmor findings outside the inline build jobs (workflow-level permissions at
  build.yml:47-48, remaining `persist-credentials` checkouts) — handled in #798's stack.
