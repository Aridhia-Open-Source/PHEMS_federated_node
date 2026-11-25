# Federated Node tooling

The Federated Node is the deployable unit that runs analysis against a site's data. `nexus-api` owns records and rules, Dagster carries out the pipeline, and task pods run the partner-supplied analysis. The shared `nexus.fednode` package provides the common settings and command-line entry points used by the node components.

## Configure a node with fncli

[`fncli`](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/tree/main/nexus/fednode/cli) is the development and operations CLI. It reads bootstrap files, validates the target node, and calls nexus-api; it does not write the database directly.

Typical development flow:

```bash
fncli apply -f node.yaml       # create or update the declared resources
fncli diff -f node.yaml        # inspect the changes first
fncli demo -f node.yaml        # walk one pull request through the pipeline
fncli delete -f node.yaml      # soft-delete declared resources
```

Apply is additive. Delete is a soft delete and reports resources that cannot be removed because another project still uses them. Secret values are never stored in bootstrap files; the files refer to Kubernetes or node secrets by name. See [Using fncli](Using-fncli.md) and [Set up a project](Set-Up-A-Project.md) for the file layout and project workflow.

## Shared settings

The API, Dagster and fncli use the same nested settings model. Settings are grouped by concern (for example database, Keycloak, task isolation and git providers), are loaded from the component's supported environment/configuration sources, and are validated before startup. A setting that is not used by a component is not silently accepted as a second configuration path: use the owning component's documented group.

The node target and defaults are separate from global resources. This lets one bootstrap file describe the node while project, repository, dataset and trigger files remain reusable. The file split and the additive/delete rules are recorded in [ADR 0025](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0025-fncli-bootstrap-files-diff-apply-delete.md), [ADR 0026](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0026-apply-is-additive-delete-is-a-soft-delete.md) and [ADR 0027](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0027-bootstrap-files-split-by-stage-of-use.md).

## Database layout

The chart uses one PostgreSQL server but separate databases and roles for nexus-api, Keycloak and Dagster. The component-specific values are configured under `db`, `keycloak.db` and `dagster.postgresql`; the old single `fnDagster.db` setting is not supported. The `*-db-init` hooks create or check the databases and roles, depending on `db.manageRolesAndDatabases`.

For an external PostgreSQL server, provide the administrator secret when the chart manages roles and databases. If a DBA owns them, set `db.manageRolesAndDatabases: false` and provide the component credentials as documented in [Deploy: Core](Deploy-Core.md). Never commit database passwords or generated values files.

## Useful references

- [Deploy: Core](Deploy-Core.md) for chart installation and database setup.
- [Operations](Operations.md) for health checks, upgrades and recovery.
- [fncli README](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/tree/main/nexus/fednode/cli) for command details.
- [ADR 0039](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0039-fednode-shared-package.md) for the shared package boundary.
