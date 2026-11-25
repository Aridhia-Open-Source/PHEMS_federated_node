# Full Flux demo

This example builds the complete local GitOps demonstration from a fresh
checkout:

```text
Docker Gitea + Actions runner
    -> installation PR
    -> Flux GitRepository/Kustomization
    -> Federated Node HelmRelease
    -> project/resources PR
    -> Nexus operator
    -> merged trigger PR
    -> Dagster task and results PR
```

The script deliberately creates the two visible pull requests in the external
Gitea repository:

1. `demo-install` installs the Federated Node through Flux.
2. `bootstrap-demo-resources` declares the Gitea provider, demo repositories,
   OAuth-backed NodeSecrets and `demo-gitea` Project.

## Prerequisites

Run the normal checkout setup once:

```bash
mise run configure
mise run setup
```

The script expects Docker, kind, the local registry, kubectl, Helm, Flux, age,
SOPS, kustomize and yq through the pinned mise tools. It uses the current
kind context and the `.dev.env` values. It does not run `mise run deploy`;
Flux is the only installer of the Federated Node release.

## Run it

From the repository root:

```bash
./flux/examples/demo.sh
```

The default mode pauses after creating each Gitea PR. Open the printed URL,
inspect the validation workflow and merge the PR, then press Enter. This keeps
the GitOps event visible and avoids silently merging changes.

For an unattended local demonstration, explicitly opt in to API merges:

```bash
./flux/examples/demo.sh --auto-merge
```

The script is safe to rerun against the same local state. It reuses the
persistent Gitea data in `.local/gitea/`, the generated site checkout in
`.local/fn-site/`, and the cluster's `~/.fn/data`. If a previous run is
partially installed, inspect it first:

```bash
mise run flux status
kubectl get gitrepositories,kustomizations -n flux-system
kubectl get helmrelease -n fn
kubectl get gitproviders,nodesecrets,repositories,projects -n fn-operator
```

## What the script does

1. Starts or reuses the `fn` kind cluster, builds chart dependencies and
   publishes the chart to the local registry.
2. Starts external Docker Gitea at <http://localhost:4000> and its Actions
   runner. Gitea state is retained under `.local/gitea/`; the generated admin
   password is in `.local/gitea/admin-password`.
3. Installs Flux and creates `gitea_admin/fn-site` with an empty `main` branch
   and the complete application on `demo-install`.
4. Creates the installation PR. After it merges, Flux reconciles the site and
   installs the Helm release.
5. Starts temporary port-forwards for Nexus API, Dagster and Keycloak when
   they are not already available.
6. Deploys and seeds the `demo-db` experiment database.
7. Creates `bootstrap-demo-resources`, containing
   `flux/examples/site/node-config/`, and opens the second PR.
8. Runs `fncli gitea setup` after that PR is merged. This creates
   `demo-trigger-repo` and `demo-results-repo` in Gitea and writes their OAuth
   credentials into Kubernetes Secrets.
9. Starts all Dagster sensors, creates and merges the demo trigger PR, waits
   for the task and watches delivery of the results PR.

The deployment repository files use `gitea-bootstrap:3000`, which is reachable
from the cluster. Host-side fncli uses `GITEA_LOCAL_URL=http://localhost:4000`
to translate those URLs for the researcher-side Gitea operations.

## Useful URLs

| Component | URL |
|---|---|
| External Gitea | <http://localhost:4000> |
| Site repository | <http://localhost:4000/gitea_admin/fn-site> |
| Flux-managed Nexus UI | <http://localhost:8088/nexus-ui/> |
| Keycloak admin console | <http://localhost:8080/admin/master/console/> |
| Dagster | <http://localhost:3000> |

Use the first-user credentials from `.dev.env` for the Nexus UI and Keycloak.
The automated task flow uses the generated `dagster` system-user password from
the `dagster-keycloak-creds` Secret.

## Clean up

To remove the Flux-managed application and external Gitea containers:

```bash
mise run flux down
mise run gitea-down
```

To remove the cluster and its persistent data as well:

```bash
mise run cluster down
```

The script never deletes `.local/gitea/` or `~/.fn/data`; remove those
specific paths only when a genuinely empty demo is required.
