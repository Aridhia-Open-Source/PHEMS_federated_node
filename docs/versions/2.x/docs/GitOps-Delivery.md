# GitOps delivery

How a node is upgraded, reverted and configured from a git repository with Flux ([ADR 0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0031-gitops-delivery-with-helm-and-flux.md)).

- A **site repository** holds what the site owns: a `HelmRepository` (where the chart comes from), a `HelmRelease` that pins the chart version, and the site's `values.yaml`. `site-example/` is the template.
- **Flux**, in the node's cluster, pulls the site repository and upgrades the node to whatever it pins.
- The site repository lives in the cluster's own **Gitea**, so Flux needs no access to anything outside the cluster for it.
- The chart and images come from `ghcr.io/aridhia-open-source`, published by a `v*` tag (`.github/workflows/build.yml`).

## On a site

1. Install the node's prerequisites and Flux (`flux install`).
2. Copy `site-example/` into a repository in the node's Gitea. In `helmrepository.yaml` set `url: oci://ghcr.io/aridhia-open-source/charts` and drop `insecure`. In `values.yaml` drop the `image` and `tag` lines and set the site's own values. Secret values never go in it: they stay in Kubernetes Secrets, referenced by name.
3. Point Flux at it: `flux create source git` and `flux create kustomization`, as `scripts/flux.sh up` does.
4. Upgrade: bump `version` in `helmrelease.yaml` and merge. Revert: `git revert` that commit. A failed upgrade is retried twice, then rolled back.
5. Config: edit `values.yaml` and merge. The values ConfigMap name carries a hash of its content, so every values change upgrades the release.
6. An upgrade that breaks Gitea also stops Flux from pulling the fix, since the site repository lives there. Recover by hand: `flux suspend helmrelease federated-node -n fn`, `helm rollback <release> <last good revision> -n fn`, push the fix to the site repository, `flux resume helmrelease federated-node -n fn`.

### Site repository hosted elsewhere

When the site repository lives outside the cluster (GitHub, the site's own git), Gitea keeps a pull mirror of it and Flux pulls from the mirror. Commits land in the site repository; Gitea picks them up within 10 minutes.

```bash
SITE_REPO_TOKEN=<read token> mise run mirror-to-gitea https://github.com/<org>/<site-repo>.git
mise run mirror-to-gitea      # sync now instead of waiting
```

- The script reads `NAMESPACE` (the node's namespace) from `.dev.env`, and uses the current `kubectl` context.
- The token is only needed for a private repository.
- Point Flux at the mirror as in step 3, with `--url=http://gitea.<namespace>.svc:4000/gitea_admin/fn-site.git --branch=main`: the site repository's default branch must be `main`.
- The Gitea pod must reach the site repository's host: Gitea does not use the chart's `proxy` or `customCA` yet.
- Charts and images still come from `ghcr.io`.

On the dev cluster, run `mise run mirror-to-gitea URL` before `mise run flux up`: `up` finds the fn-site mirror and points Flux at it.

## On the dev cluster

Needs a dev node from `mise run deploy` (it includes Gitea) owned by your worktree, and `mise run setup` for the pinned `flux` CLI. Don't run `tilt up` while Flux owns the release: it redeploys the dev images over it.

```bash
mise run flux publish 0.0.1-dev   # this chart, as version 0.0.1-dev, into the kind registry
mise run flux up                  # install Flux, push site-example/ to Gitea as gitea_admin/fn-site, adopt the release
mise run flux status              # Flux objects and the release's helm history
```

`site-example/helmrelease.yaml` uses the release name and namespace `mise run deploy` used, so Flux adopts that release rather than installing a second node. From then on `mise run deploy` and `mise run teardown` refuse until `mise run flux down`, which removes Flux and the site repository and leaves the release as it is.

To run the loop, clone the site repository (`http://localhost:4000/gitea_admin/fn-site.git`, login `gitea_admin`, password from `kubectl get secret gitea-admin -n fn -o jsonpath='{.data.password}' | base64 -d`), then:

- **Upgrade:** `mise run flux publish 0.0.2-dev`, set `version: "0.0.2-dev"` in `helmrelease.yaml`, push. `helm history fn-dev -n fn` shows the new revision.
- **Revert:** `git revert HEAD`, push.
- **Config:** change a value in `values.yaml`, push.

Flux looks every minute; `flux reconcile kustomization fn-site -n flux-system --with-source` skips the wait.

The dev site values pin the dev images (`latest`), so a version bump there changes only the chart.
