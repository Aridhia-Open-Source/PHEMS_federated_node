# 0032. Node config as declarative files, applied by an operator

Status: Proposed, 2026-11-11.

## Context

- **Node config is what a node needs before it can run a task:** git providers, secrets (where credentials live), trigger and results repositories, datasets, and projects with their assignments ([0006](0006-global-resources-and-project-resources.md)).
- **In dev it is set up by fncli from env files** ([0018](0018-fncli-dev-ops-tool.md)). About 30 `TEST_*` and related variables in `.dev.env` drive group commands such as `setup-project`, `setup-backend` and `setup-gitea`, and their step commands.
- **Those commands only create.** Each step reuses what exists and never changes it: edit `TEST_RESULTS_TARGET_DIR`, run again, and nothing changes. There is no preview, and removal is a separate `teardown-*` command.
- **One project per env file.** A second project or a different repository means another env file or editing this one.
- **On a deployed node it is set up by hand,** through the API or the UI. Nothing records what a node should hold, so it cannot be reviewed, repeated on another node, or reverted.
- **Delivery moves to Flux** ([0031](0031-gitops-delivery-with-helm-and-flux.md)). A revert there puts the chart back; config should follow the same path.

## Decision

- **Node config is described in declarative YAML files**, kept in git: providers, secrets, repositories, datasets and projects. A secret entry names where its value comes from, never the value.
- **On a node, the config becomes custom resources.** CRDs: `GitProvider`, `Secret` (a reference only), `Repository`, `Dataset`, `Project`. The site's Helm values hold the config in the same shape as the files, and the chart templates it into custom resources.
- **An operator applies them.** It is written in Python with Kopf, and uses the nexus-api client fncli and Dagster already share. For each resource it creates, updates, and on removal soft-deletes the record in nexus-api ([0008](0008-enabled-revoked-and-soft-delete.md)).
- **Removal is safe on a shared node.** The operator never deletes with `?force=true`. A global resource another project still uses is refused by nexus-api with a 409; the operator reports it in the resource's status and keeps the record.
- **Removal and drift.** Removing an entry from the values and upgrading deletes it, so a revert works for config as it does for the chart. Edits made in the UI that differ from the config are put back.
- **The operator's scope is nexus-api only.** It never touches the git server: no repository creation, no Gitea OAuth apps. Those stay dev-only fncli steps, or a one-time job run by the site.
- **CRDs ship as chart templates** (or a small separate chart), because Helm installs files in `crds/` but never upgrades them.
- **fncli reads the same files in dev.** `fncli diff`, `apply` and `delete` take a file, write the custom resources to the dev cluster (diff with `kubectl diff`), and the operator does the rest, so dev runs the production path. The env-driven `setup-*` and `teardown-*` commands go.
- **fncli keeps the non-config work:** opening and merging test pull requests, `demo`, `delete-gitea-token`, and the Gitea repository and OAuth setup.

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

### Proposed: config files

Shared pieces, used by any number of projects:

```yaml
version: 1
providers:
  - type: github
    uri: https://github.com
secrets:
  analysis-repo-creds:                    # a GitHub App, shared by both repositories
    values:
      APP_ID:          {env: GH_APP_ID}
      INSTALLATION_ID: {env: GH_INSTALLATION_ID}
      PRIVATE_KEY:     {file: ~/.config/fn/analysis-app.private-key.pem}
repositories:
  triggers:
    - uri: https://github.com/example-org/analysis-requests
      secret: analysis-repo-creds
  results:
    - uri: https://github.com/example-org/analysis-results
      secret: analysis-repo-creds
```

A project and what it is assigned:

```yaml
version: 1
projects:
  - name: cohort-study
    datasets: [omop-cdm]
    repositories:
      triggers:
        - repository: https://github.com/example-org/analysis-requests
          watch_dir: specs/
          base_branch: main
      results:
        repository: https://github.com/example-org/analysis-results
        target_dir: results/
        base_branch: main
```

In dev:

```bash
fncli diff   -f globals.yaml                  # preview what would change
fncli apply  -f globals.yaml                  # provider, repositories, credentials
fncli apply  -f projects/cohort-study.yaml    # the project and its assignments
fncli delete -f projects/cohort-study.yaml    # soft delete; skips what another project still uses
```

### Proposed: the same config on a deployed node

The site repository ([0031](0031-gitops-delivery-with-helm-and-flux.md)) holds it as Helm values. The shape is the file's; only the secret sources change, from local env and files to Kubernetes Secrets, which SOPS or External Secrets fill.

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
            watch_dir: specs/
            base_branch: main
        results:
          repository: https://github.com/example-org/analysis-results
          target_dir: results/
          base_branch: main
```

The chart turns each entry into a custom resource, for example:

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
- **See the state:** `kubectl get projects,repositories,datasets -n fn` shows each resource and whether it is synced, with the operator's message when it is not.
- **Without Flux:** `helm upgrade --install` with the same values has the same effect.

## Consequences

What it replaces:

- **The env-driven setup:** the `setup-*` and `teardown-*` commands, their step commands, and the `TEST_*` variables behind them.
- **Setting up deployed nodes by hand** through the API or the UI.
- **Hand-built removal and drift logic:** no ownership tags, state store or prune code in fncli. Kubernetes and Helm track what exists, and the operator only maps each resource to nexus-api.

What it gives:

- **Node config is reviewed, repeated and reverted in git,** the same way as the chart version.
- **One path for dev and deployed nodes:** config always goes through the operator, so dev tests what runs at a site.
- **Several projects share** providers, repositories and datasets, without one env file each.
- **Status on each resource:** `kubectl get` shows what is synced and why something is not.
- **Secrets stay out** of the config and the custom resources: a `Secret` names where the value lives.

What it does not need:

- **Flux is optional.** The config-file workflow works on any node with the chart installed: `fncli apply -f` in dev, or `helm upgrade` with the values on a site that upgrades by hand. Flux only automates the `helm upgrade`.

What it costs:

- **The operator is a new component** to build, test and run in every node. It is small: the nexus-api client already exists, and Kopf handles the watch loop, retries and status.

## Alternatives considered

- **fncli applies the files straight to nexus-api, with no operator:** works in dev, but a deployed node then needs fncli run by hand or as a Flux Job, and removal needs ownership tags or a state store built by hand. The operator gets removal and drift from Kubernetes and Flux.
- **Keep the env files and add update and preview to the step commands:** still one project per file, and a second engine beside anything that runs on a deployed node.
- **Crossplane:** needs a nexus-api provider, which is the same effort as our own operator, and it is heavier to run.
- **An operator that also creates git repositories and OAuth apps:** not needed on a deployed node, and the hardest part to get right.

Delivery of the chart and the operator itself is covered in [0031](0031-gitops-delivery-with-helm-and-flux.md).
