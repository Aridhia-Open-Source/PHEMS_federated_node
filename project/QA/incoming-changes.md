# What is changing: the in-flight work, for QA

The `dagster-develop` branch runs today as it is documented in `DEMO.md`: node config goes in with `fncli apply`, you deploy with `mise run deploy`, and one administrator does everything. Four sets of pull requests change that. They are all open as drafts or in review; this page says what each one means for a tester. When they land, [at-a-glance.md](at-a-glance.md) and [README.md](README.md) (the QA plans) describe the new state.

## At a glance

| Area | What changes for a tester | Pull requests |
|---|---|---|
| Sign-in and access (auth) | Keycloak roles, token checks, grants, Cedar rules. Many calls now return 403 or 409 where they used to succeed | #694 (umbrella), #714, #682, #683, #686, #742, #743, #684, #687, #685, #688, #689, #733 |
| Node config as code (operator) | `kubectl apply` replaces `fncli apply`; the node follows the cluster resources | #700 (umbrella), #716, #696, #718, #690, #698, #699, #697 |
| Deploy by commit (Flux) | A site repository drives the release; secrets come from SOPS | #701 (umbrella), #715, #691, #702, #725, #726, #706, #703, #717 |
| Docs and QA | ADRs, wiki pages and these QA pages | #744, #747, #745, #746 |
| CI only | Faster tests and a merge queue. No behaviour change | #738, #739, #740, #741 |

Not part of this round: infrastructure provisioning (Pulumi, #707 and its stack) is parked.

## Auth: who may do what

- **Sign-in.** The node uses the Keycloak realm `FederatedNode` with the roles SuperUser, Administrator, Service, Users and Dagster (groups under `/roles`). The API accepts access tokens only: an expired token, a refresh token or a token from another realm gets 401. (#683, #686)
- **Owner groups are gone.** The old owner-group model is removed from the API, the chart, the realm setup and the UI. (#682)
- **Grants.** Every record that can be owned (project, dataset, git provider, secret, repository) has grants: `read`, `write`, `execute`, `assign`, `manage`. Creating a record gives its creator `manage`. Responses now carry `created_by` and `owned_by` instead of `owner`. The owner's `manage` cannot be removed; only a SuperUser can claim or reassign an owner. (#684)
- **Cedar rules decide.** Writes and reads are checked against the grants and the role; a refused request is a 403, and a protected owner or a refused state change is a 409. A user who only has `read` can `GET` but not `PATCH` or `DELETE`. (#687, #685, #688)
- **Named rules and a decision log (not built yet).** Rules get names such as `dataset.execute.revoked`, roles map to permissions in `roles.yaml`, and each decision is logged with the rule that made it. (#733 is still a placeholder.)
- **Config internals.** nexus-api and Dagster each read their environment through one `settings` object. No behaviour change is intended. (#742, #743)

Test with: a plain user, an Administrator and a SuperUser against the same project; the token cases above; removing the owner's `manage`; claiming an owner as a SuperUser.

## Operator: node config as code

- A Kubernetes operator applies `GitProvider`, `NodeSecret`, `Dataset`, repository and `Project` resources to nexus-api. `kubectl get fn -A` shows each as Synced with the operator's message. (#690)
- The old `fncli apply`, `diff` and `delete` for node files go away; `fncli gitea setup` and the project and dataset commands stay. (#690, #699)
- Updating a resource updates the API record; deleting one soft-disables it. A `NodeSecret` that a repository still uses stays in `Terminating` with a 409 until the repository is gone. The operator reads Secrets made by SOPS. (#698)
- Shared clients: nexus-api, Dagster and the operator use one client for the API and one outbound layer for git hosts, which retries when the API answers 429. (#696, #718)
- On grants: records the operator creates are owned by the Service role. (#697, last in the stack)

Test with: applying the sample resources under `config/`, changing and deleting them, turning the operator off, running a task end to end afterwards.

## Flux: deploy by commit

- `mise run flux publish`, `flux sops-key`, `flux up` and `flux down` publish the chart, adopt the running release and hand it back. A commit to the site repository upgrades or rolls back. (#691)
- An in-cluster Gitea can mirror the site repository. (#702)
- Secrets are SOPS-encrypted in the site repository and decrypted by Flux; the old copy of Secrets between namespaces is removed. External Secrets is built but SOPS is the default. (#725, #703, #717)
- Site pipelines build and test the site repository. (#726)

Test with: publish a version, adopt, bump the version in the site repository, roll back, and check a SOPS Secret reaches the pod that reads it.

## Docs that go with these

- New wiki pages: Sign-In-And-Roles, Granting-Access, Auth-Setup, Node-Config, Node-Secrets, Deploy-With-Flux, Flux-Dev-Loop, Flux-Secrets, Flux-Site-Repository-Mirror; rewritten Run-Locally and Using-fncli. (#744)
- ADRs: Flux deploy (0031), node config through an operator (0032), Pulumi (0034, parked), OIDC authentication (0035), Keycloak roles and accounts (0036), Cedar grants and policies (0037), the outbound client layer (0038), several node instances in one cluster (0039, draft). (#744, #747)
- The manual test plans in this folder were written before the auth work. Where one expects an older response, write down what you saw.
