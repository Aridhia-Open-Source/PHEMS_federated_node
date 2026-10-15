# Handover: dagster-moonshot (global resources) and the Gitea mirror

Written at the end of a long design session, for the next Claude (or person) who picks this up. Read this first, then ADR 0019.

## Branches

| Branch | What it is |
|---|---|
| `ccr-417a04ba-ugt8hk` | Design docs only, cut from `dagster-develop`. ADRs 0018, 0019, 0020 and this handover. **Start here.** |
| `dagster-develop-preview` | `dagster-develop` plus all 15 open PRs merged (#526, #528, #529, #530, #531, #532, #533, #534, #535, #543, #544, #545, #546, #547, #548). Not #523, the promotion PR. The base for the moonshot. |
| `dagster-moonshot` | **Does not exist yet.** The feature branch for the schema rewrite. Cut it from `dagster-develop-preview`, then merge `ccr-417a04ba-ugt8hk` into it for the docs. |

Setup:

```
git fetch origin
git checkout -b dagster-moonshot origin/dagster-develop-preview
git merge origin/ccr-417a04ba-ugt8hk      # docs only; the README index may need a trivial merge
```

If the open PRs land on `dagster-develop` first, rebase onto that instead; the preview branch is only a stand-in.

## What we are doing

1. **The moonshot** (ADR [0019](../decisions/0019-global-resources-and-shared-pull-requests.md)): make secrets, trigger repositories, results repositories and datasets global, assign them to projects through `project_trigger_repositories`, `project_results_repositories` and `project_datasets`, store pull requests once per repository with per-project fan-out, and give each assignment `enabled` (a person's switch) and `revoked` (access withdrawn). Active means `enabled` and not `revoked`. Revoking never touches `enabled`. Revoking affects only that resource, never the project.
2. **The Gitea mirror** (ADR [0020](../decisions/0020-gitea-mirror-service.md)): a separate, self-contained service. It mirrors a GitHub repository's merged PRs into the node's Gitea over outbound-only connections and fires signed webhooks at the webserver. **Out of scope for the moonshot.** It depends on moonshot stages 1 to 5 and on a Gitea spike. Do not start it.

The moonshot is **not needed for the beta demo**. It is a branch being built in parallel, to be reviewed and merged after the demo. If it is not green and reviewed by the cut-off, the demo ships on the current design.

## Constraints from the owner

- Keep the Dagster sensors' structure as is. The review found they do change a little: DTOs, `active` filtering, and the ingest sensor polling once per global repository. That is accepted. Do not restructure them.
- Resource tables keep natural names: `trigger_repositories`, `results_repositories`, `datasets`, `secrets` are global; the project-scoped ones are `project_trigger_repositories`, `project_results_repositories`, `project_datasets`. No clever mixin names.
- Disabling is per resource and never stops the project.
- The owner's style: short answers, lead with the answer, no waffle, no padding with hypothetical edge cases. Only raise a problem you can trace to a concrete code path.

## State of things

- **Nothing in the moonshot is built.** There is no code, only ADRs.
- **No tests have been run** on `dagster-develop-preview`, webserver or Dagster. First job: get the webserver tests green there (they need Postgres; PR #532 isolates test runs). Docker worked in the previous environment but Docker Hub rate-limited it; `mirror.gcr.io` worked for images.
- **Merge conflict resolutions in the preview branch** that the owner should confirm (all were judgment calls):
  - `k8s/federated-node/templates/requirements-check.yaml`: #528 deletes the `github-token`/`GH_TOKEN` requirement check, #526 rewords it. The preview branch takes the deletion.
  - `dev.db/clients.py`: #535 deletes it, #531 edited it. The preview branch deletes it; the fncli and Dagster clients already use #531's `{"pull_requests": [...]}` body.
  - `dagster/app/config.py`, `dagster-env-config.yaml`, `test_config.py` (#545 vs #528): kept `SensorStatusConfig` and `DAGSTER_SENSORS_INITIAL_STATUS`, dropped the legacy `SensorConfig` and `GH_DELIVERY_REPO`.
  - `TaskSpec` became `TaskSpecRequest` (#547) in the webserver; two test fixtures combine #531's body shape with #547's removal of `payload`.
  - `PullRequestResultState` is gone (#548 renamed it `PullRequestResultStep`) and `PullRequestSpec` is gone (#547); the Dagster `models/__init__.py` exports neither.
  - Checks done: everything compiles, no conflict markers, no new undefined names versus `dagster-develop` (pyflakes). That is all.
- **The review in [moonshot-review.md](moonshot-review.md) is model-generated.** Treat its line numbers and counts as leads and verify them. Its conclusions are in ADR 0019.

## Suggested first steps

1. Cut `dagster-moonshot`, get the webserver tests running and green.
2. Write the contract tests from ADR 0019 ("Contract tests to add first") and land them with no behaviour change. They pin the flat API shape, plus a JSON fixture check that the Dagster and fncli models parse the same responses.
3. Ask the owner to settle the eight "Decisions still needed" in ADR 0019, at least 1 to 5 before stages 5 and 6.
4. Work the stages in order, one commit per stage: global secrets, then datasets, results repositories, trigger repositories, `pull_requests` and fan-out, the `enabled`/`revoked` behaviour, the ingest sensor, and last fncli, `openapi.json`, docs and ADR updates.

## Open PRs that overlap the moonshot

Heavy: #548, #547, #543, #534, #531, #535. Light: #526, #533, #529, #530. Independent: #528, #532, #544, #545, #546. If a colleague merges some into `dagster-develop` first, rebase onto that before touching the overlapping files.

## Things decided and not to relitigate

- Webhooks from GitHub straight into the node: rejected, the node stays outbound-only.
- Argo CD for mirroring: rejected, it sees git refs and no pull request objects.
- One mirror per project (a Gitea org per project): only the fallback if the moonshot is not done.
- A `disabled_reason` string: rejected in favour of the `revoked` boolean.
- Real-time updates were never a requirement.
