# Deploy with Flux

A site's node is installed, upgraded, reverted and configured from a git repository by Flux, running in the node's own cluster. Why, and what was weighed against it: [ADR 0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0031-gitops-deployment-with-flux.md).

- The **site repository** holds what the site owns: a `HelmRepository` (where the chart comes from), a `HelmRelease` that pins the chart version, the site's `values.yaml`, and its Secrets, SOPS-encrypted. `site-example/` is the template.
- **Flux** pulls the site repository and upgrades the node to whatever it pins. Nothing reaches into the cluster.
- The site repository lives in the node's own **Gitea**, so Flux needs nothing outside the cluster for it. If the site keeps it elsewhere, Gitea mirrors it: [Flux site repository mirror](./Flux-Site-Repository-Mirror).
- The chart and images come from `ghcr.io/aridhia-open-source`, published by a `v*` tag.

## Set up a site

1. Deploy the node once with Helm ([Deploy: Core](./Deploy-Core)), with `gitea.enabled: true` in its values. Flux adopts this release later.
2. Install Flux: `flux install`.
3. Make the site's age key and load it into Flux: [Flux secrets](./Flux-Secrets).
4. Make the site repository in the node's Gitea from `site-example/`:
   - `helmrepository.yaml`: `url: oci://ghcr.io/aridhia-open-source/charts`, drop `insecure`.
   - The namespace `fn` appears in `helmrelease.yaml`, `helmrepository.yaml`, `first-user-secret.yaml` and the `configMapGenerator` in `kustomization.yaml`: change all of them to the node's namespace.
   - `helmrelease.yaml`: `releaseName` is the one step 1 used, so Flux adopts that release rather than installing a second node; `version` is the chart version to run.
   - `values.yaml`: drop the `image` and `tag` lines, set the site's own values. Secret values never go here.
   - `first-user-secret.yaml`: fill in the first user's login and encrypt it before the first commit.
5. Point Flux at it, as `scripts/flux.sh up` does:

   ```bash
   flux create secret git fn-site-auth -n flux-system --url=<site repo URL> --username=<user> --password=<token>
   flux create source git fn-site -n flux-system --url=<site repo URL> --branch=main --secret-ref=fn-site-auth
   flux create kustomization fn-site -n flux-system --source=GitRepository/fn-site --path=./ --prune=true \
     --decryption-provider=sops --decryption-secret=sops-age
   ```

   The URL inside the cluster is `http://gitea.<namespace>.svc:4000/<owner>/<repo>.git`.

## Run it

- **Upgrade:** bump `version` in `helmrelease.yaml` and merge. A failed upgrade is retried twice, then rolled back.
- **Revert:** `git revert` that commit. Reverting the chart does not undo database migrations.
- **Config:** edit `values.yaml` and merge. The values ConfigMap's name carries a hash of its content, so every values change upgrades the release.
- **Check:** `flux get helmreleases -n <namespace>` and `helm history <release> -n <namespace>`.
- **Recover:** an upgrade that breaks Gitea also stops Flux pulling the fix. By hand: `flux suspend helmrelease federated-node -n <namespace>`, `helm rollback <release> <last good revision> -n <namespace>`, push the fix to the site repository, `flux resume helmrelease federated-node -n <namespace>`.

## Pull request checks

`site-example/` carries one check for the site repository's pull requests, with a pipeline for each CI system: `.github/workflows/validate.yml` (GitHub Actions), `azure-pipelines.yml` (Azure DevOps) and `.gitea/workflows/validate.yml` (Gitea Actions). Keep the one for the site's CI system and delete the others. All three run `ci/install-tools.sh` (pinned helm, kustomize and yq, fetched with curl) and then `ci/validate.sh`, which fails the pull request when:

- `kustomize build` fails;
- the chart version the `HelmRelease` pins does not render with the site's values (`helm template`, which also checks them against the chart's values schema);
- a file `.sops.yaml` says to encrypt is in plain text.

It needs no cluster, keys or cloud credentials. On Azure DevOps with an Azure Repos repository, add the pipeline as a build validation branch policy on `main`.

`renovate.json` makes Renovate open a pull request for each new chart version. Run Renovate as the site's CI system allows (the GitHub app, or self-hosted on Azure DevOps or Gitea); the client merging the pull request is their sign-off.

## Known gaps

- Gitea needs direct outbound access to the site repository's host when it mirrors one: it does not use the chart's `proxy` or `customCA` yet.
- No nexus UI image is published yet: keep `nexus.ui.enabled: false` (the default).

## Try it locally

[Flux dev loop](./Flux-Dev-Loop): the same setup against the dev cluster, with `mise run flux`.
