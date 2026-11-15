# GitOps delivery

How a node is upgraded, reverted and configured from a git repository, run end to end on the development cluster ([ADR 0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0031-gitops-delivery-with-helm-and-flux.md)). Nothing here needs GitHub or a cloud account:

- The bundled **Gitea** hosts a copy of this repository and a test **site repository**, `fn-site`.
- **Gitea Actions** runs the release workflow, `.gitea/workflows/release.yml`, on a tag `v*`.
- The **kind registry** holds the released images and the chart, as OCI artifacts.
- **Flux**, in the same cluster, upgrades the node to whatever the site repository pins.

On a real site the git server, the registry and the CI are outside the node. Only Flux and the site repository are the site's.

## One registry, three names

| Name | Used by |
|---|---|
| `kind-registry:5000` | The release workflow's job, and Flux's source-controller (pods, through the cluster DNS) |
| `localhost:5001` | Your shell, and the image values in `site-example/values.yaml` (the kind nodes' containerd mirror) |

If the release job cannot resolve `kind-registry`, set `RELEASE_REGISTRY`, `INSECURE_REGISTRY` and `CHART_REPO` in the workflow to the registry's IP on the kind network: `docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' kind-registry`.

## Before you start

- A dev node from a fresh `mise run deploy`, owned by your worktree (`mise run deploy-owner`). Its values must have `gitea.actions.enabled` and `gitea.actions.runner.enabled` true, as `dev.example.values.yml` does.
- `mise run setup` has installed the pinned `flux` CLI.

## 1. Publish two releases

Two builds of one commit, so going back and forth between them never meets an incompatible migration:

```bash
mise run mirror-to-gitea --tag v0.0.1-dev
# wait for the run to go green: http://localhost:4000/gitea_admin/federated-node/actions
mise run mirror-to-gitea --tag v0.0.2-dev
```

`mirror-to-gitea` pushes this working tree (uncommitted changes to tracked files included) to `gitea_admin/federated-node` and tags it. The tag starts the workflow: `docker buildx bake release` with the images tagged by the version, then `helm package` and `helm push`. When both runs are green:

```bash
helm show chart oci://localhost:5001/charts/federated-node --version 0.0.2-dev --plain-http
curl -s http://localhost:5001/v2/nexus_api/tags/list
```

## 2. Hand the node to Flux

```bash
mise run flux up
```

It installs Flux, pushes `site-example/` to Gitea as `gitea_admin/fn-site`, and points Flux at it. The site's `HelmRelease` has the release name and namespace `mise run deploy` used, so Flux adopts that release instead of installing a second node. It ends when the `HelmRelease` is Ready at `0.0.1-dev`. `helm history fn-dev -n fn` shows the upgrade from the dev images to the released ones.

From now on `mise run deploy` and `mise run teardown` refuse: the release is Flux's. `mise run flux status` shows the Flux objects and the release history.

Clone the site repository to make the changes below. The login is `gitea_admin`, with the password from `kubectl get secret gitea-admin -n fn -o jsonpath='{.data.password}' | base64 -d`:

```bash
git clone http://localhost:4000/gitea_admin/fn-site.git && cd fn-site
```

Flux looks at the repository every minute. To skip the wait after a push:

```bash
flux reconcile kustomization fn-site -n flux-system --with-source
```

## 3. Upgrade: bump the version

In `helmrelease.yaml`, set `version: "0.0.2-dev"`, then commit and push.

Expect:

- `flux get hr -n fn` shows `0.0.2-dev`.
- `helm history fn-dev -n fn` has a new revision with chart `federated-node-0.0.2-dev`.
- The pods run the `0.0.2-dev` images.

## 4. Go back: git revert

```bash
git revert --no-edit HEAD && git push
```

Expect a further revision at `0.0.1-dev`. Flux upgrades to the reverted version; it is not a `helm rollback`, so the history keeps both moves. Reverting the chart does not revert the database: this works because both builds have the same migrations.

## 5. Config: add a project, then remove it

This needs the operator (PR #656): add `operator.enabled: true` to `values.yaml` first, and push. The project names repositories and a dataset that must already be in nexus-api, here the e2e ones.

Add to `nodeConfig` in `values.yaml`, then commit and push:

```yaml
  projects:
    - name: gitops-demo
      datasets: [dev-dataset]
      repositories:
        results:
          repository: http://gitea.fn.svc:4000/gitea_admin/fn-results-repo
          targetDir: results/gitops-demo/
          baseBranch: main
```

Expect:

- `values.yaml` becomes a new ConfigMap and Flux upgrades the release at once.
- `kubectl get fn -n fn` lists the `Project` `gitops-demo` with `Synced` true.
- The project is in nexus-api (the UI at `http://localhost:8088`, or `GET /projects`).

Then `git revert --no-edit HEAD && git push`. The `Project` resource is gone after the upgrade, and the operator soft-deletes the project in nexus-api.

## When an upgrade fails

A failed upgrade is retried twice, then rolled back by Flux to the last good revision (`upgrade.remediation` in `helmrelease.yaml`). In an emergency:

```bash
flux suspend hr federated-node -n fn
helm rollback fn-dev -n fn
# fix the site repository, then
flux resume hr federated-node -n fn
```

Locally, Gitea is part of the release Flux upgrades, so an upgrade restarts the source Flux reads from. Expect one failed reconcile per upgrade; the next interval succeeds. A real site's git server is outside the node.

## Back to the dev loop

```bash
mise run flux down
mise run deploy
```

`flux down` removes Flux and the `fn-site` repository and leaves the release as it is. `deploy` then upgrades it back to the dev images.
