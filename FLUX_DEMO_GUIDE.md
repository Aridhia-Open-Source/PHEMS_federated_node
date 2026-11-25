# Local Flux, Gitea and Operator Demo

This guide demonstrates the cumulative `verify/all` branch:

```text
Gitea site repository -> pull request -> merge to main
    -> Flux GitRepository/Kustomization
    -> HelmRelease
    -> Nexus operator reconciliation
    -> Keycloak-authenticated Federated Node
```

The demo uses the local kind cluster named `fn`.

## 1. Start from a clean deployment

Run from the cumulative worktree:

```bash
cd /home/georgeeddie/Development/Aridhia-Open-Source/PHEMS/fn-worktrees/verify-all

mise run flux down       # harmless if Flux is not installed
mise run teardown
mise run deploy
```

Show the plain Helm deployment:

```bash
kubectl get pods -A
helm status fn-dev -n fn
kubectl get deployment -n fn-operator nexus-operator
```

Useful browser views:

| Component | URL |
|---|---|
| Gitea | <http://localhost:4000> |
| Keycloak | <http://localhost:8080> |
| Nexus UI | <http://localhost:8088> |
| Dagster | <http://localhost:3000> |
| Flux | no bundled web UI; use `flux` and `kubectl` commands |

Start the port-forwards if they are not already running:

```bash
mise run portfwd
```

## 2. Publish the chart and let Flux adopt the release

In the worktree:

```bash
mise run flux publish 0.0.1-dev
mise run flux up
mise run flux status
```

`flux up` installs Flux, creates the local SOPS key, creates the Gitea
`gitea_admin/fn-site` repository, and points Flux at its `main` branch.

Show Flux adoption:

```bash
kubectl get gitrepository,kustomization -n flux-system -o wide
kubectl get helmrelease -n fn federated-node -o wide
helm history fn-dev -n fn
```

Expected:

- `fn-site` GitRepository: `Ready=True`
- `fn-site` Kustomization: `Ready=True`
- `federated-node` HelmRelease: `Ready=True`
- Helm history contains the Flux-managed `0.0.1-dev` release

In the Gitea UI, open:

```text
http://localhost:4000/gitea_admin/fn-site
```

Log in as `gitea_admin`. Retrieve the generated password with:

```bash
kubectl get secret gitea-admin -n fn \
  -o jsonpath='{.data.password}' | base64 -d
echo
```

## 3. Use the persistent local site checkout

The Flux setup keeps the site repository in the gitignored directory:

```text
.local/fn-site/
```

Create a site change:

```bash
cd .local/fn-site
git checkout -b demo-change

# Make a visible change, for example edit values.yaml or helmrelease.yaml.
git add .
git commit -m "demo: change site configuration"
```

Push the branch to Gitea:

```bash
GITEA_AUTH="Authorization: Basic $(printf '%s:%s' gitea_admin \
  "$(kubectl get secret gitea-admin -n fn -o jsonpath='{.data.password}' | base64 -d)" \
  | base64 -w0)"
git -c "http.extraHeader=$GITEA_AUTH" push -u origin demo-change
```

Show the branch in the Gitea UI:

```text
http://localhost:4000/gitea_admin/fn-site/branches
```

## 4. Open and validate the Gitea pull request

In the Gitea UI:

1. Open `gitea_admin/fn-site`.
2. Select **Pull Requests**.
3. Select **New Pull Request**.
4. Set the base branch to `main`.
5. Set the compare branch to `demo-change`.
6. Create the pull request.

The site repository contains this Gitea Actions workflow:

```text
.gitea/workflows/validate.yml
```

It runs `ci/validate.sh`, which validates the site manifests, Helm values,
and SOPS files.

Show the pull request and checks in:

```text
http://localhost:4000/gitea_admin/fn-site/pulls
```

Gitea Actions requires a registered `act_runner`. If no runner is installed,
the PR still demonstrates the Gitea review gate, but the check remains queued.

## 5. Merge the pull request and let Flux reconcile it

After the PR check passes, merge it in the Gitea UI. Flux tracks `main`, not
the unmerged PR branch.

Force an immediate reconciliation instead of waiting for the one-minute poll:

```bash
flux reconcile source git fn-site -n flux-system
flux reconcile kustomization fn-site -n flux-system --with-source
```

Show the merged revision and Helm reconciliation:

```bash
kubectl get gitrepository,kustomization -n flux-system -o wide
kubectl get helmrelease -n fn federated-node -o wide
helm history fn-dev -n fn
```

The Gitea source commit, Kustomization revision, and HelmRelease update are
the key screens to show for the GitOps part of the demo.

## 6. Show operator reconciliation

The HelmRelease values enable the Nexus operator. Show the controller:

```bash
kubectl get deployment -n fn-operator nexus-operator
kubectl logs -n fn-operator deploy/nexus-operator --tail=80
```

Show the custom resources reconciled by the operator:

```bash
kubectl get gitproviders,nodesecrets,projects,repositories -A -o wide
```

Expected operator-managed resources have reconciled/synced status. The
operator configuration is visible in the Gitea site repository under:

```text
config/
values.yaml
```

## 7. Show Keycloak authentication and SOPS secrets

Show the Keycloak and realm-init pods:

```bash
kubectl get pods -n keycloak
kubectl logs -n keycloak -l app=keycloak-realm-init --tail=80
```

Show the Flux-decrypted secrets:

```bash
kubectl get secret keycloak-first-user keycloak-superuser -n keycloak
```

The Keycloak UI is available at:

```text
http://localhost:8080
```

Do not print secret values during the demo.

## 8. Optional end-to-end task trigger

Start the sensors:

```bash
fncli start-sensor --group all
```

Trigger the example merged pull request:

```bash
fncli trigger --pr --merge --watch triggers/examples/demo.json
```

Show the task flow in:

- Dagster UI: <http://localhost:3000>
- Nexus UI: <http://localhost:8088>
- Gitea results pull request: <http://localhost:4000/gitea_admin>

The expected acceptance result is 15/15 checks and a results pull request in
Gitea.

## 9. Return control from Flux

When finished:

```bash
mise run flux down
```

This removes Flux and the Gitea `fn-site` repository but keeps the local
checkout at `.local/fn-site/`. The checkout is gitignored and can be reused
by the next demo.

To remove the plain Helm deployment and its data as well:

```bash
mise run teardown
```

