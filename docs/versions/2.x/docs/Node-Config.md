# Node config

A node's config is what it needs before it can run a task: git providers, secrets, trigger and results repositories, datasets, and projects with what they are assigned. With the **nexus operator** on, that config lives in git as Helm values, and the operator applies it to nexus-api. This page is for the admin who keeps that config. For the secrets, see [Node secrets](./Node-Secrets).

The design is in [ADR 0032](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/716).


## How it works

- The chart turns each `nodeConfig` entry into a Kubernetes custom resource of group `fn.aridhia.com/v1alpha1`: `GitProvider`, `NodeSecret`, `Repository`, `Dataset` or `Project`.
- They live in the operator's own namespace, `fn-operator` (`global.namespaces.operator`), never the release namespace.
- The operator watches them. For each one it creates or updates the record in nexus-api, and on removal soft-deletes it.
- It logs in to nexus-api as its own Keycloak user, `fn-operator` (an Administrator for now). The chart generates its password, and the credential rotation job rotates it.
- Without the operator, set the node up through the API instead: [Set up a project](./Set-Up-A-Project). Do not mix the two for the same record.


## Turn it on

```yaml
operator:
  enabled: true
```

Then `helm upgrade` as usual. The image tag follows the chart's. The CRDs ship in the chart, and a pre-upgrade hook keeps them current.


## Write the config

Put `nodeConfig` in the site's values. No secret values go here: a secret names the Kubernetes Secret its values are in.

```yaml
nodeConfig:
  providers:
    - name: github
      type: github                # or gitea
      uri: https://github.com
  secrets:
    analysis-repo-creds:
      fromSecret: {name: analysis-github-app}   # keys APP_ID, INSTALLATION_ID, PRIVATE_KEY
    omop-db-creds:
      fromSecret: {name: omop-db-login}         # keys USERNAME, PASSWORD
  repositories:                   # named by type and uri unless given a name
    triggers:
      - uri: https://github.com/example-org/analysis-requests
        secret: analysis-repo-creds
    results:
      - uri: https://github.com/example-org/analysis-results
        secret: analysis-repo-creds
  datasets:
    - name: omop-cdm
      type: postgres
      host: omop-db.example.org
      port: 5432
      secret: omop-db-creds
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

Providers, secrets, repositories and datasets are global: any number of projects can use them. A project only assigns them. The full field list is in the chart's `values.yaml` and the CRDs in `k8s/federated-node/crds/`.


## Change it

| To | Do |
|---|---|
| Add or change | Edit the values, review and merge, `helm upgrade`. With Flux ([ADR 0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/701)), the merge is the upgrade |
| Remove | Delete the entry, or `git revert` the commit that added it, then upgrade. The operator soft-deletes the record |
| See the state | `kubectl get fn -n fn-operator` |

Flux is optional: `helm upgrade` by hand with the same values does the same.

Removal is never forced. A global record that a project still uses is refused by nexus-api; its resource stays `Terminating`, with the reason in `Message`, and the operator retries every minute. Remove the project's use of it first.

Edits made in the UI or the API stay until the resource next changes, when the operator writes its own values back.


## Check it

```sh
kubectl get fn -n fn-operator
```

Each resource shows `Synced` and, when it is not synced, a `Message`: a NodeSecret's Kubernetes Secret that is missing, a dataset a project names that is not there yet, or an error from nexus-api. The operator retries every minute, so fix the cause and wait. Its log is `kubectl logs -n fn-operator deploy/nexus-operator`. With Flux, its annotations on the resource are in the log and the resource's events.


## Turn it off or uninstall

Setting `operator.enabled: false`, or `helm uninstall`, keeps the records in nexus-api. A hook first stops the operator and strips the finalizers from its resources, so they go without being soft-deleted. The chart renders `nodeConfig` only while the operator is on.

To remove records, delete their entries and upgrade **before** turning the operator off.


## In development

Dev uses the same operator and resources, as YAML files in `config/`, applied with kubectl:

```sh
kubectl diff   -f config/demo.yaml     # preview
kubectl apply  -f config/demo.yaml
kubectl delete -f config/demo.yaml     # soft delete
```

[Run locally](./Run-Locally) walks through it.
