# Handover: dagster-moonshot (global resources) and the Gitea mirror

Written at the end of a long design session, for the next Claude (or person) who picks this up. Read this first, then ADR 0019.

## Branches

You are on `dagster-moonshot`: `dagster-develop-preview` plus the design docs. That is all you need.

| Branch | What it is |
|---|---|
| `dagster-moonshot` | The feature branch for the schema rewrite. Work here. Contains ADRs 0018, 0019, 0020 and this handover. |
| `dagster-develop-preview` | `dagster-develop` plus all 15 open PRs merged (#526, #528, #529, #530, #531, #532, #533, #534, #535, #543, #544, #545, #546, #547, #548). Not #523, the promotion PR. The base of the moonshot. |
| `ccr-417a04ba-ugt8hk` | The docs-only branch the ADRs were written on, cut from `dagster-develop`. Already merged into `dagster-moonshot`; ignore it. |

If the open PRs land on `dagster-develop` first, rebase onto that; the preview branch is only a stand-in.

## What we are doing

1. **The moonshot** (ADR [0019](../decisions/0019-global-resources-and-shared-pull-requests.md)): make secrets, trigger repositories, results repositories and datasets global, assign them to projects through `project_trigger_repositories`, `project_results_repositories` and `project_datasets`, store pull requests once per repository (with base branch and changed paths) with per-project fan-out, and give each assignment `enabled` (a person's switch) and `revoked` (access withdrawn). Active means `enabled` and not `revoked`. Revoking never touches `enabled`. Revoking affects only that resource, never the project.
2. **The Gitea mirror** (ADR [0020](../decisions/0020-gitea-mirror-service.md)): a separate, self-contained service. It mirrors a GitHub repository's merged PRs into the node's Gitea over outbound-only connections. It has its own database and API and no knowledge of the node; anyone can subscribe a webhook endpoint, and the node can also just poll the mirror as a normal Gitea repository. **Out of scope for the moonshot.** It does not depend on the moonshot; it is gated on a Gitea spike. Build plan: [gitea-mirror-plan.md](gitea-mirror-plan.md). Do not start it until told.

The moonshot is **built** (stages 0-8b complete). Stages 0-8 sit on the stacked moonshot branches, local only.

## Constraints from the owner

- No flat compatibility API. The API exposes the real model (global resources, plus `/projects/<id>/...` assignments with the global resource nested) and the Dagster sensors use it directly: ingest polls each global repository once, evaluate and launch loop over active assignments, delivery uses the task's results assignment. The sensors get simpler; the models and endpoints change more.
- Resource tables keep natural names: `trigger_repositories`, `results_repositories`, `datasets`, `secrets` are global; the project-scoped ones are `project_trigger_repositories`, `project_results_repositories`, `project_datasets`. No clever mixin names.
- Disabling is per resource and never stops the project.
- The owner's style: short answers, lead with the answer, no waffle, no padding with hypothetical edge cases. Only raise a problem you can trace to a concrete code path.

## State of things

- **The moonshot is built** (stages 0-8b). See [moonshot-plan.md](moonshot-plan.md) and the commit log in each stage's PR for what changed.
- Each stage ran its own test files only, never whole suites. fncli tests could not run (no pytest) and the shell seed scripts were only syntax-checked. See each stage's commit message.
- **Merge conflict resolutions in the preview branch** that the owner should confirm (all were judgment calls):
  - `k8s/federated-node/templates/requirements-check.yaml`: #528 deletes the `github-token`/`GH_TOKEN` requirement check, #526 rewords it. The preview branch takes the deletion.
  - `dev.db/clients.py`: #535 deletes it, #531 edited it. The preview branch deletes it; the fncli and Dagster clients already use #531's `{"pull_requests": [...]}` body.
  - `dagster/app/config.py`, `dagster-env-config.yaml`, `test_config.py` (#545 vs #528): kept `SensorStatusConfig` and `DAGSTER_SENSORS_INITIAL_STATUS`, dropped the legacy `SensorConfig` and `GH_DELIVERY_REPO`.
  - `TaskSpec` became `TaskSpecRequest` (#547) in the webserver; two test fixtures combine #531's body shape with #547's removal of `payload`.
  - `PullRequestResultState` is gone (#548 renamed it `PullRequestResultStep`) and `PullRequestSpec` is gone (#547); the Dagster `models/__init__.py` exports neither.
  - Checks done: everything compiles, no conflict markers, no new undefined names versus `dagster-develop` (pyflakes). That is all.
- **The review in [moonshot-review.md](moonshot-review.md) is model-generated.** Treat its line numbers and counts as leads and verify them. Its conclusions are in ADR 0019.

## Suggested first steps

1. Get the webserver tests running and green on this branch.
2. Write the contract tests from ADR 0019 ("Contract tests to add first") and land them with no behaviour change. They pin the endpoints that do not change shape and write the target shapes as `xfail(strict=True)` tests that each stage flips, plus a JSON fixture check that the Dagster and fncli models parse the same responses.
3. The eight open decisions are settled in ADR 0019, section 11. Read them before building.
4. Work the stages in order, one commit per stage: global secrets, then datasets, results repositories, trigger repositories, `pull_requests` and fan-out, the `enabled`/`revoked` behaviour, the ingest sensor, and last fncli, `openapi.json`, docs and ADR updates.

## Open PRs that overlap the moonshot

Heavy: #548, #547, #543, #534, #531, #535. Light: #526, #533, #529, #530. Independent: #528, #532, #544, #545, #546. If a colleague merges some into `dagster-develop` first, rebase onto that before touching the overlapping files.

## Things decided and not to relitigate

- Webhooks from GitHub straight into the node: rejected, the node stays outbound-only.
- Argo CD for mirroring: rejected, it sees git refs and no pull request objects.
- One mirror per project (a Gitea org per project): only the fallback if the moonshot is not done.
- A `disabled_reason` string: rejected in favour of the `revoked` boolean.
- Real-time updates were never a requirement.
- A flat compatibility API (assignment id as `id`): dropped. Also settled: cross-project loops forbidden, revoke immediate, global edits need every assigned project locked and drained, migration folds 002 into the baseline (ADR 0019, section 11).
