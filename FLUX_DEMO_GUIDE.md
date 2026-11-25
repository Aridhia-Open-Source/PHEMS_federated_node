# Local Flux and Gitea Demo

> **Automated version:** [`flux/examples/README.md`](flux/examples/README.md)
> and [`flux/examples/demo.sh`](flux/examples/demo.sh) run this complete flow,
> including the two Gitea pull requests, operator resources and demo trigger.
> Use the manual sections below when presenting or troubleshooting individual
> stages.

This demo starts with a kind cluster and registry, but no Federated Node
release. An independent Docker Gitea and Actions runner host the site
repository. Flux watches `main`; merging one Gitea pull request installs the
application.

```text
Docker Gitea + Actions runner
    -> merged site PR
    -> Flux GitRepository/Kustomization
    -> HelmRelease
    -> Nexus operator and Keycloak
```

The commands below run from the repository root in the `verify/all` worktree.

## 1. Prepare the cluster and images

Use an existing kind cluster named `fn`, or create one:

```bash
mise run cluster up
mise run helm deps
mise run images
```

Do not run `mise run deploy`: the application must be installed by Flux.

If reusing a previous test, clean the application and Flux state first:

```bash
mise run flux down || true
mise run teardown || true
mise run gitea-down || true
```

## 2. Start independent Gitea and Actions

```bash
mise run gitea-bootstrap
```

This starts:

- Gitea at <http://localhost:4000>
- an Actions runner in Docker, joined to the `kind` network
- persistent local state under `.local/gitea/` (gitignored)

The administrator is `gitea_admin`. The password is in:

```text
.local/gitea/admin-password
```

The repository is created by `mise run flux up`, after Flux has been
installed. This keeps the bootstrap independent from the application release.

## 3. Publish the chart and bootstrap Flux

Publish the chart to the local registry, then install Flux and configure it to
watch the Gitea repository:

```bash
mise run flux publish 0.0.1-dev
mise run flux up
```

`flux up` creates the namespaces, Flux controllers, cluster SOPS key, and
`gitea_admin/fn-site`. It commits only the validation workflow to `main`, then
pushes the complete application as the `demo-install` candidate branch.

Verify that Flux is watching an intentionally empty application repository:

```bash
kubectl get gitrepository,kustomization -n flux-system -o wide
flux get sources git -n flux-system
flux get kustomizations -n flux-system
kubectl get helmrelease -n fn
```

There should be no HelmRelease yet.

## 4. Open the first installation PR

Open the Gitea repository:

<http://localhost:4000/gitea_admin/fn-site>

Log in with `gitea_admin` and the password from `.local/gitea/admin-password`.
Create a pull request from `demo-install` into `main`.

The candidate branch contains:

- `helmrelease.yaml` and `helmrepository.yaml`
- site values with embedded Gitea disabled
- SOPS-encrypted first-user and superuser Secrets
- namespaces and operator configuration
- `.gitea/workflows/validate.yml`

The Actions workflow runs `ci/validate.sh`. Show the pull request and its
check at:

<http://localhost:4000/gitea_admin/fn-site/pulls>

After merging, show workflow runs and live job logs at:

<http://localhost:4000/gitea_admin/fn-site/actions>

If the check remains queued, inspect the runner:

```bash
docker logs fn-demo-act-runner --tail=80
```

## 5. Merge the PR and show the first install

After the check passes, merge the PR in the Gitea UI. Do not merge it from a
script: the merge is the visible GitOps event in this demo.

Flux automatically polls the GitRepository and applies `main` on its
configured five-second interval. For an immediate demo result, you can
optionally force reconciliation:

```bash
flux reconcile source git fn-site -n flux-system
flux reconcile kustomization fn-site -n flux-system --with-source
```

Show the source revision, Kustomization, and HelmRelease:

```bash
kubectl get gitrepository,kustomization -n flux-system -o wide
kubectl get helmrelease -n fn federated-node -o wide
helm history fn-dev -n fn
```

Flux has no bundled web UI in this demo. Watch its resources from the
terminal:

```bash
watch kubectl get gitrepository,kustomization -n flux-system
watch kubectl get helmrelease -n fn
```

Expected result:

- `fn-site` GitRepository is `Ready=True`
- `fn-site` Kustomization is `Ready=True`
- `federated-node` HelmRelease is `Ready=True`
- Helm history contains the Flux-managed `0.0.1-dev` release

Flux has now installed the application from the merged Gitea revision; no
plain `mise run deploy` was used.

## 6. Show operator and authentication reconciliation

Useful Kubernetes views:

```bash
kubectl get pods -A
kubectl get deployment -n fn-operator nexus-operator
kubectl get gitproviders,nodesecrets,projects,repositories -A -o wide
kubectl get pods -n keycloak
kubectl logs -n keycloak -l app=keycloak-realm-init --tail=80
```

Useful browser views:

| Component | URL |
|---|---|
| Gitea and PR | <http://localhost:4000> |
| Keycloak | <http://localhost:8080> |
| Nexus UI | <http://localhost:8088> |
| Dagster | <http://localhost:3000> |
| Flux | no bundled UI; use `flux` and `kubectl` |

Start port-forwards if needed:

```bash
mise run portfwd
```

Show that the SOPS files were decrypted into Kubernetes Secrets without
printing their values:

```bash
kubectl get secret keycloak-first-user keycloak-superuser -n keycloak
```

## 7. Optional task execution

The application task flow can be demonstrated after the installation is
healthy:

```bash
fncli start-sensor --group all
fncli trigger --pr --merge --watch triggers/examples/demo.json
```

Show the run in the Dagster UI, the task in the Nexus UI, and the results PR
in Gitea.

## 8. Clean up

Remove Flux and the application release, then stop the independent Docker
services:

```bash
mise run flux down || true
mise run teardown || true
mise run gitea-down
```

The generated site checkout and Gitea data remain under `.local/` so the
demo can be repeated without losing local state. Remove those specific
directories manually when a completely fresh repository is required.
