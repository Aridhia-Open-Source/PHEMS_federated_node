# 0032. Node config as declarative files, applied by an operator

Status: Proposed, 2026-11-11.

## Context

- **Node config is what a node needs before it can run a task:** git providers, secrets (where credentials live), trigger and results repositories, datasets, and projects with their assignments ([0006](0006-global-resources-and-project-resources.md)).
- **In dev it is set up by fncli from env files** ([0018](0018-fncli-dev-ops-tool.md)). About 30 `TEST_*` and related variables in `.dev.env` drive group commands such as `setup-project`, `setup-backend` and `setup-gitea`, and their step commands.
- **Those commands only create.** Each step reuses what exists and never changes it: edit `TEST_RESULTS_TARGET_DIR`, run again, and nothing changes. There is no preview, and removal is a separate `teardown-*` command.
- **One project per env file.** A second project or a different repository means another env file or editing this one.
- **On a deployed node it is set up by hand,** through the API or the UI. Nothing records what a node should hold, so it cannot be reviewed, repeated on another node, or reverted.
- **The nexus-api client lives in `dagster/app`:** the HTTP session, the retry and token-refresh adapters, the client models and the API calls. fncli, in the same package, uses it. An operator that belongs to nexus should not depend on Dagster's package.
- **Delivery moves to Flux** ([0031](0031-gitops-delivery-with-helm-and-flux.md)). A revert there puts the chart back; config should follow the same path.

## Decision

### Config

- **Node config is described in declarative YAML**, kept in git: providers, secrets, repositories, datasets and projects. A secret entry names where its value comes from, never the value.
- **The config is custom resources.** CRDs: `GitProvider`, `Secret` (a reference only), `Repository`, `Dataset`, `Project`. In dev they are YAML files in `config/`. On a deployed node the site's Helm values hold the same fields, and the chart templates them into custom resources.
- **CRDs ship as chart templates** (or a small separate chart), because Helm installs files in `crds/` but never upgrades them.
- **Dev applies them with kubectl:** `kubectl apply -f`, `kubectl diff -f` and `kubectl delete -f` on the files in `config/`. A deployed node uses `helm upgrade` with the values. The operator and the custom resources are the same in both, so dev runs the production path.
- **fncli steps back from node config.** It no longer applies or diffs it. The env-driven `setup-*` and `teardown-*` commands, their step commands and the `TEST_*` variables go.
- **fncli keeps only the work outside nexus-api config:** raising and merging pull requests, Gitea setup (repositories, OAuth apps, tokens), `demo`, `trigger`, and the QA breakage commands.

### The operator

- **An operator applies the resources.** It is written in Python with Kopf. For each resource it creates, updates, and on removal soft-deletes the record in nexus-api ([0008](0008-enabled-revoked-and-soft-delete.md)).
- **It lives in `nexus/operator/`,** with its own image and a Deployment of one replica (Kopf leader election covers a restart or a rolling update). It is not a Service, because nothing calls it. It belongs to nexus, not Dagster.
- **Removal is safe on a shared node.** The operator never deletes with `?force=true`. A global resource another project still uses is refused by nexus-api with a 409; the operator reports it in the resource's status and keeps the record.
- **Removal and drift.** Removing an entry from the values and upgrading deletes it (in dev, `kubectl delete -f`), so a revert works for config as it does for the chart. Edits made in the UI that differ from the config are put back.
- **The operator's scope is nexus-api only.** It never touches the git server: no repository creation, no Gitea OAuth apps. Those stay dev-only fncli steps, or a one-time job run by the site.

### The shared client package

- **`nexus/client/` is a package of its own** (`nexus-client`, with its own `pyproject.toml`). The HTTP session and adapters (BaseHttpAdapter, OAuthAdapter, BackendAdapter: retry and token refresh), the client models and the API calls move out of `dagster/app` into it. Dagster, fncli and the operator use it.
- **It is a path dependency, compiled with each consumer.** `scripts/pip_compile.sh` compiles the consumer's `pyproject.toml` together with `../nexus/client/pyproject.toml` (pip-compile takes several sources). That gives one hashed `requirements.txt` per image, and clashing pins fail at compile time. The consumer's `pyproject.toml` does not list nexus-client.
- **The image installs in four steps:** the hashed requirements, then the client copied in from a bake named context (`contexts = { nexus-client = "nexus/client" }`) and installed with `pip install --no-deps`, then the app with `--no-deps`, then `pip check`.
- **Local dev installs it editable:** `pip install --no-deps -e ./nexus/client`.
- **Scanning covers it.** The client's third-party dependencies are in each consumer's hashed `requirements.txt`, so Dependabot, pip-audit and image scans see them. The client itself is first-party code.
- **CI tests the client, Dagster, fncli and the operator on the same commit,** so an API or client change that breaks a consumer fails in that pull request.

### Auth and trust

- **The operator has its own identity.** It logs in to nexus-api as a Keycloak service client (client credentials) with a role limited to node config. It never uses a person's login.
- **Whoever can change the custom resources changes node config.** Two controls: review on the site repository (with Flux, a merge is the approval), and Kubernetes RBAC, where only Flux's ServiceAccount (and admins, for emergencies) may edit these kinds.
- **Changes are attributed.** nexus-api records them as the operator. The operator copies the commit and author from Flux's annotations into nexus-api's audit record.
- **Calls go through the API,** so its auth and rules apply to every change.

## Examples

### Today: env file and group commands

```bash
# .dev.env (excerpt): one project, its two repositories and its dataset
TEST_PROJECT_NAME=fn-dev
TEST_TRIGGER_REPO=fn-trigger-repo
TEST_TRIGGER_REPO_URI=http://gitea.fn.svc:4000/gitea_admin/fn-trigger-repo
TEST_TRIGGER_REPO_WATCH_DIR=specs/
TEST_TRIGGER_REPO_BASE_BRANCH=main
TEST_RESULTS_REPO=fn-results-repo
TEST_RESULTS_REPO_URI=http://gitea.fn.svc:4000/gitea_admin/fn-results-repo
TEST_RESULTS_TARGET_DIR=results/
TEST_RESULTS_REPO_BASE_BRANCH=main
DEFAULT_PROJECT_DATASET=dev-dataset
```

```bash
fncli setup-backend       # provider, secrets, repositories, dataset
fncli setup-project       # the project and its assignments
fncli open-pr --kind watched
fncli teardown-project    # the only way to remove
```

### Proposed: custom resource files in dev

Shared pieces, used by any number of projects:

```yaml
# config/globals.yaml
apiVersion: fn.aridhia.com/v1alpha1     # group name to be decided
kind: GitProvider
metadata:
  name: github
spec:
  type: github
  uri: https://github.com
---
apiVersion: fn.aridhia.com/v1alpha1
kind: Secret                            # a reference only; a GitHub App shared by both repositories
metadata:
  name: analysis-repo-creds
spec:
  fromSecret: {name: analysis-github-app}   # keys APP_ID, INSTALLATION_ID, PRIVATE_KEY
---
apiVersion: fn.aridhia.com/v1alpha1
kind: Repository
metadata:
  name: analysis-requests
spec:
  type: trigger
  uri: https://github.com/example-org/analysis-requests
  secret: analysis-repo-creds
---
apiVersion: fn.aridhia.com/v1alpha1
kind: Repository
metadata:
  name: analysis-results
spec:
  type: results
  uri: https://github.com/example-org/analysis-results
  secret: analysis-repo-creds
```

A project and what it is assigned:

```yaml
# config/projects/cohort-study.yaml
apiVersion: fn.aridhia.com/v1alpha1
kind: Project
metadata:
  name: cohort-study
spec:
  datasets: [omop-cdm]
  repositories:
    triggers:
      - repository: https://github.com/example-org/analysis-requests
        watchDir: specs/
        baseBranch: main
    results:
      repository: https://github.com/example-org/analysis-results
      targetDir: results/
      baseBranch: main
```

In dev the Kubernetes Secret that holds the values is made from local env and files, then kubectl applies the resources:

```bash
kubectl create secret generic analysis-github-app -n fn \
  --from-literal=APP_ID="$GH_APP_ID" --from-literal=INSTALLATION_ID="$GH_INSTALLATION_ID" \
  --from-file=PRIVATE_KEY=$HOME/.config/fn/analysis-app.private-key.pem

kubectl diff   -f config/globals.yaml                 # preview the change to the custom resources
kubectl apply  -f config/globals.yaml                 # provider, repositories, credentials
kubectl apply  -f config/projects/cohort-study.yaml   # the project and its assignments
kubectl delete -f config/projects/cohort-study.yaml   # soft delete; the operator keeps what another project still uses
kubectl get projects,repositories -n fn               # synced or not, with the operator's message
```

### Proposed: the same config on a deployed node

The site repository ([0031](0031-gitops-delivery-with-helm-and-flux.md)) holds it as Helm values, with the same fields as the dev files grouped by kind. The Kubernetes Secrets that hold the values are filled by SOPS or External Secrets, not by hand.

```yaml
nodeConfig:
  providers:
    - name: github
      type: github
      uri: https://github.com
  secrets:
    analysis-repo-creds:
      fromSecret: {name: analysis-github-app}   # keys APP_ID, INSTALLATION_ID, PRIVATE_KEY
  repositories:
    triggers:
      - uri: https://github.com/example-org/analysis-requests
        secret: analysis-repo-creds
    results:
      - uri: https://github.com/example-org/analysis-results
        secret: analysis-repo-creds
  projects:
    - name: cohort-study
      datasets: [omop-cdm]
      repositories:
        triggers:
          - repository: https://github.com/example-org/analysis-requests
            watchDir: specs/
            baseBranch: main
        results:
          repository: https://github.com/example-org/analysis-results
          targetDir: results/
          baseBranch: main
```

The chart turns each entry into a custom resource, the same as the dev file plus the status the operator fills in:

```yaml
apiVersion: fn.aridhia.com/v1alpha1     # group name to be decided
kind: Project
metadata:
  name: cohort-study
spec:
  datasets: [omop-cdm]
  repositories:
    triggers:
      - repository: https://github.com/example-org/analysis-requests
        watchDir: specs/
        baseBranch: main
    results:
      repository: https://github.com/example-org/analysis-results
      targetDir: results/
      baseBranch: main
status:
  synced: true
  nexusId: 12
  message: ""
```

Usage:

- **Add or change:** edit the values, open a pull request, merge. Flux runs `helm upgrade`; the operator creates or updates the record in nexus-api.
- **Remove:** delete the entry, or `git revert` the commit that added it. Helm deletes the `Project`; the operator soft-deletes it in nexus-api.
- **Who changed it:** nexus-api's audit record shows the operator as the actor, with the commit and author Flux annotated on the resource.
- **See the state:** `kubectl get projects,repositories,datasets -n fn` shows each resource and whether it is synced, with the operator's message when it is not.
- **Without Flux:** `helm upgrade --install` with the same values has the same effect. Dev uses `kubectl apply -f` on the files instead.

### The shared client package in a build

The client's own dependencies, in `nexus/client/pyproject.toml`:

```toml
[project]
name = "nexus-client"
dependencies = [
    "requests~=2.32",
    "pydantic~=2.0",
    "pydantic-settings~=2.0",
]
```

The compile step for a consumer, here Dagster, run in `dagster/`. The consumer's `pyproject.toml` lists no nexus-client; the client is only a source here, so its dependencies land in the hashed file:

```bash
pip-compile --generate-hashes --output-file=requirements.txt \
    pyproject.toml ../nexus/client/pyproject.toml
```

The image, with the client passed in as a bake named context:

```hcl
target "dagster" {
  context  = "dagster"
  contexts = { nexus-client = "nexus/client" }
}
```

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt        # hashed, the client's dependencies included
COPY --from=nexus-client . /opt/nexus-client
RUN pip install --no-cache-dir --no-deps /opt/nexus-client
COPY . .
RUN pip install --no-cache-dir --no-deps . && pip check
```

In local dev: `pip install --no-deps -e ./nexus/client`.

## Consequences

What it replaces:

- **The env-driven setup:** the `setup-*` and `teardown-*` commands, their step commands, and the `TEST_*` variables behind them.
- **fncli's part in node config:** it no longer applies or diffs it. `kubectl` does that in dev and Helm on a node.
- **Setting up deployed nodes by hand** through the API or the UI.
- **Hand-built removal and drift logic:** no ownership tags, state store or prune code in fncli. Kubernetes and Helm track what exists, and the operator only maps each resource to nexus-api.
- **The client inside `dagster/app`:** it moves to `nexus/client/`.

What it gives:

- **Node config is reviewed, repeated and reverted in git,** the same way as the chart version.
- **One path for dev and deployed nodes:** config always goes through the operator, so dev tests what runs at a site.
- **Several projects share** providers, repositories and datasets, without one env file each.
- **Status on each resource:** `kubectl get` shows what is synced and why something is not.
- **Secrets stay out** of the config and the custom resources: a `Secret` names where the value lives.
- **One API client** for Dagster, fncli and the operator: retry, token refresh and the API calls in one place, tested together.
- **Attributed changes:** nexus-api's audit record shows the operator, with the commit and author behind each change.

What it does not need:

- **Flux is optional.** The config workflow works on any node with the chart installed: `kubectl apply -f` in dev, or `helm upgrade` with the values on a site that upgrades by hand. Flux only automates the `helm upgrade`.
- **Publishing the client.** It is installed from the repository, not from an index.

What it costs:

- **The operator is a new component** to build, test and run in every node. It is small: the client code already exists, and Kopf handles the watch loop, retries and status.
- **Moving the client is a one-time change** to the imports in Dagster and fncli.
- **Every consumer build needs the client's source:** the bake named context for images, and the second `pyproject.toml` in the compile step.
- **RBAC on the custom resource kinds is part of the node's security setup.** It has to stay limited to Flux's ServiceAccount and admins, because whoever can edit these kinds changes node config.

## Alternatives considered

- **fncli applies the files straight to nexus-api, with no operator:** works in dev, but a deployed node then needs fncli run by hand or as a Flux Job, and removal needs ownership tags or a state store built by hand. The operator gets removal and drift from Kubernetes and Flux.
- **Keep the env files and add update and preview to the step commands:** still one project per file, and a second engine beside anything that runs on a deployed node.
- **Crossplane:** needs a nexus-api provider, which is the same effort as our own operator, and it is heavier to run.
- **An operator that also creates git repositories and OAuth apps:** not needed on a deployed node, and the hardest part to get right.
- **ConfigMaps instead of CRDs:** untyped, no schema validation, no status, and no RBAC per kind.
- **Publishing `nexus-client` to PyPI:** versioned and hashed, but every API change that needs a client change becomes a release and a version bump in each consumer, and the images lag. Worth it only when something outside the repository needs the client.
- **A client generated from `openapi.json`:** the models alone could be generated, but the `requests` adapters (retry, token refresh) do not fit generated httpx clients.
- **A uv workspace:** one lockfile for everything, but it replaces the pip-compile setup.
- **The operator inside the nexus-api image, using nexus-api's own DTOs:** no separate image, but the operator then ships with the API, and Dagster and fncli keep a client of their own, so there are two.

Delivery of the chart and the operator itself is covered in [0031](0031-gitops-delivery-with-helm-and-flux.md).
