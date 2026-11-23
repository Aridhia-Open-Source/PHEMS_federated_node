# QA at a glance: the Federated Node beta

A one-page briefing for testers. It assumes the auth, operator and Flux work has landed. The detailed manual cases are in [README.md](README.md) and the files next to it; this page says what the node is, what to look at first and where things are.

## What the node is

A Kubernetes service that runs analysis tasks against local datasets and returns the results through git. Researchers never touch the data: they open a pull request with a task spec, the node runs it next to the data, and the results come back as a pushed branch plus a results pull request that a person reviews.

- **nexus-api** (FastAPI) owns the record and the rules: projects, datasets, repositories, secrets, triggers, tasks, results.
- **Keycloak** signs people and services in. **nexus-ui** is the admin UI.
- **Dagster** watches the git host, launches one task per merged pull request and delivers the results.
- Deployed as one Helm chart; Flux can deploy it from a site repository (Gitea in the cluster, SOPS-encrypted secrets).

## The flow to demo (10 minutes)

1. **Sign in** as the first user (administrator) in nexus-ui or with a token from Keycloak.
2. **Set up a project**: a git provider, a dataset, a secret and a repository. Two ways: the UI/API, or the operator: `kubectl apply` a `Project`, `Dataset`, `GitProvider` or `NodeSecret` and the node follows (`kubectl get fn -A` shows each as Synced).
3. **Grant access**: add a `read` grant for a plain user. That user now sees the project; anyone else gets a 403.
4. **Run a task**: merge a task pull request in the project repository (the `demo` task, `fncli demo`). Watch the sensor tick in the Dagster UI, the run, then the **results pull request** on the git host.
5. **Revoke a dataset** and merge another task pull request: the run is refused.
6. **Deploy by commit** (if Flux is on): bump a chart version in the site repository and watch the release roll out; roll it back with a second commit.

## Who can do what

- **Roles** (Keycloak groups): SuperUser, Administrator, Service (the operator), Users, Dagster.
- **Grants** say who can touch a record: `read`, `write`, `execute`, `assign`, `manage`. Creating a record gives its creator `manage`; the owner's `manage` cannot be removed; only a SuperUser can claim or reassign an owner.
- **Cedar rules** decide every request from the grants and the role. Each rule has a name (for example `dataset.execute.revoked`) and every decision is logged with the rule that made it. The roles map to permissions in `roles.yaml`.
- Refusals are specific: 403 for a missing permission, 409 for a protected owner or a refused state change.

## Postman

`mise run postman` writes a filled environment and a collection built from nexus-api's OpenAPI spec (both gitignored, in `project/QA/postman/`). It takes `baseUrl`, `username` and `password` from `.postman.env`, or from the dev cluster's first Keycloak user. Import both into Postman; the pre-request script handles the sign-in so every request carries a token. The calls are described in the wiki page Using-The-API.

## Where to read more

- **Wiki** (docs site, 2.x): Sign-In-And-Roles, Granting-Access, Auth-Setup, Node-Config, Node-Secrets, Deploy-With-Flux, Researcher-Guide, Operations, Using-The-API.
- **Decision records** (`project/decisions/`): the Flux deploy (0031), node config through an operator (0032), OIDC authentication (0035), Keycloak roles and accounts (0036), Cedar grants and policies (0037), the outbound client layer (0038).
- **Manual test plans**: [README.md](README.md) here, one file per area (sign-in and admin actions, pull requests and task creation, secrets and quarantine, enabled and revoked, failure paths, operator and node config). [known-issues.md](known-issues.md) lists what is already known to be rough.
- **Automated tests**: [../TESTING.md](../TESTING.md) says what the unit, integration and end-to-end suites cover, so manual cases start where those stop.

## Rough edges to expect

- The nexus-ui image may not be published for the beta cluster; the API, Postman and `kubectl` paths work without it.
- Infrastructure provisioning (Pulumi) is not built yet; External Secrets is built but SOPS is the default.
- Some manual plans were written before the auth work and may not match the new 403 and 409 responses. Write down what you see where they differ.

## What to ask the testers

Which environment they will test on, which role they will test as, what they have already covered, and whether they want API-first (Postman) or UI-first scripts.
