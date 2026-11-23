# QA glossary and where to find things

First, every document in one table; then the words you will meet while testing the Federated Node (FN). It assumes the in-flight auth, operator and Flux work has landed; terms from that work say so.

## Where to find everything

All on the branch `qa/tester-pack`.

| What | Link |
|---|---|
| Start here (10-minute demo) | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/project/QA/at-a-glance.md |
| What changed since develop | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/project/QA/since-develop.md |
| What is changing (in-flight work) | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/project/QA/incoming-changes.md |
| QA README and test plans | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/project/QA/README.md |
| Postman setup folder | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/tree/qa/tester-pack/project/QA/postman |
| Postman script | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/scripts/postman.sh |
| End-to-end tests README | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/dagster/fncli/tests/e2e/README.md |
| Automated testing overview | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/project/TESTING.md |
| Wiki as a site | https://aridhia-open-source.github.io/PHEMS_federated_node/docs/qa-tester-pack/ |
| Wiki pages (source) | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/tree/qa/tester-pack/docs/versions/2.x/docs |
| All ADRs | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/tree/qa/tester-pack/project/decisions |
| Demo walkthrough (today's flow) | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/DEMO.md |
| fncli README | https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/qa/tester-pack/dagster/fncli/README.md |

## Access

- **Keycloak**: the identity provider. It signs people and services in. Our realm is `FederatedNode`.
- **Role**: a Keycloak group under `/roles` that says what kind of user someone is. **SuperUser** can claim or reassign owners. **Administrator** manages the node. **Service** is the operator and other system accounts. **Users** are ordinary users. **Dagster** is Dagster's own account.
- **Access token / refresh token**: the API accepts access tokens only. A refresh token, an expired token or a token from another realm gets 401.
- **Grant**: a record that a user or group has a **relation** on one record. Relations: `read`, `write`, `execute`, `assign`, `manage`, and `operate` (turn a project on or off).
- **Owner**: whoever holds `manage` on a record. `created_by` is who made it, `owned_by` is who owns it now. The owner's `manage` cannot be removed.
- **Cedar**: the rule engine that decides each request from the grants and the role. The rules are fixed in the repository and reviewed like code.
- **Named rule / decision log**: a Cedar rule with a name such as `dataset.execute.revoked`; every decision is logged with the name of the rule. `roles.yaml` maps roles to permissions (not built yet).
- **403 / 409**: 403 means you lack permission. 409 means a protected owner or a refused state change.

## Records

- **Project**: a body of work that groups datasets, repositories and secrets.
- **Dataset**: a database a task may run against, with its connection secret.
- **Global and project resources**: global ones (datasets, git providers, secrets, repositories) are shared; a project uses them through assignments.
- **Git provider**: the GitHub or Gitea host the node talks to.
- **Repository**: a git repository the node uses. A **trigger repository** is where task pull requests are merged; a **results repository** is where results go.
- **Secret**: a credential kept in a Kubernetes Secret and referenced by name; values never appear in the API or in git.
- **Enabled, revoked, soft delete**: switches that stop a dataset or project from being used. Delete never removes the record; it disables it.

## Running a task

- **Task spec**: the file in a pull request that says what to run (image, command, datasets).
- **Trigger**: the rule that turns a merged pull request into a task.
- **Task**: one run of a spec against its datasets. It stays pinned to the configuration it started with.
- **Sensor**: a Dagster watcher: ingest, evaluate, launch, run status, delivery. They start stopped; `fncli start-sensor --group all` starts them.
- **Run, tick, run key**: Dagster words. A sensor checks on each tick, a run is one execution, a run key stops the same pull request running twice.
- **Results pull request**: where the node delivers results (a pushed branch plus a pull request, up to 10 MB zipped). A person reviews it; it is the human gate.

## Config and deploy

- **Operator**: a Kubernetes controller. It applies resources (`Project`, `Dataset`, `GitProvider`, `NodeSecret`, repositories) to the API. `kubectl get fn -A` shows each as **Synced**.
- **Finalizer**: the Kubernetes hold that keeps a deleted resource around until the operator has finished. A `NodeSecret` that a repository still uses stays Terminating.
- **Helm chart / values**: how the node is installed; the values file is the site's settings.
- **Flux**: a GitOps controller that deploys the chart from a **site repository** (the git repository that describes one node). A commit upgrades or rolls back.
- **Gitea**: a small git host. It is the demo git provider and can mirror the site repository inside the cluster.
- **SOPS**: encrypts secrets so they can live in git; Flux decrypts them. **External Secrets** is the optional vault route.
- **Pulumi**: infrastructure provisioning. Not built yet.
- **kind / Tilt**: the local dev cluster and its live-reload loop.

## Tools and documents

- **fncli**: the dev and ops command line. Today it also applies node config (`fncli apply`); with the operator, config moves to `kubectl apply`.
- **Postman collection**: built from the API's OpenAPI spec by `mise run postman`.
- **mise**: the task runner (`mise run deploy`, `mise run postman`).
- **ADR**: an architecture decision record; each explains one design choice.
- **Wiki**: the 2.x user and operator docs.
- **Stack**: a chain of pull requests, each on the one before. The in-flight ones are auth, operator, Flux and CI.
