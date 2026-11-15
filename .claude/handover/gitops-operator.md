# Handover: gitops operator (ADR 0032) then Flux (ADR 0031)

Resume: read this file, then `git log --oneline origin/dagster-develop..HEAD`. Worktree: `../gitops-operator`, branch `feat/gitops-operator`, draft PR into `dagster-develop`.

**Goal:** every change to a node, both version and config, goes in as a git commit that can be reviewed and reverted.

## Rules
- Commit and push after each step; update this file in the same commit.
- After each step's push: a background review agent (Fable, or Opus by usage band) posts inline PR comments (**Claude:** prefix) on that step's diff.
- Unit tests for changed files only. No e2e. No cluster teardown or takeover (`mise run deploy-owner` first).
- No Co-Authored-By lines. Imports at module top. Copy existing patterns; no defensive code.
- Stop at 95% of the 5h usage limit (`$CLAUDE_CONFIG_DIR/usage.json`), push, and update this file.

## Steps
Part 1, operator (ADR 0032):
1. [x] Delete ADR 0033 and its index row.
2. [x] Move the shared API client from `dagster/app` to `nexus/client/` (own pyproject; path dep compiled with each consumer; bake named context). Dagster and fncli tests pass.
3. [x] CRDs + `nodeConfig` chart templates, schema, helm-unittest.
4. [x] Kopf operator in `nexus/operator/`: sync to nexus-api, soft delete, status, Keycloak service client, RBAC, image, Tilt.
5. [~] Move experiment setup / e2e / demo onto `kubectl apply`; drop fncli `diff/apply/delete`; docs.

Part 2, Flux (ADR 0031), local with Gitea first:
6. [x] Gitea Actions + `act_runner` in the bundled Gitea (dev only).
7. [~] Release workflow in Gitea Actions publishes chart + images as OCI.
8. [~] Flux in kind + test site repo in Gitea (HelmRelease, values, `nodeConfig`); scripted.
9. [~] Prove the loop: bump, revert, config edit. Doc it.
10. Later, separate PR: GitHub Actions port, release bundle, SOPS, Pulumi (not started yet).

## Refined plan
Detail per step (files, decisions, risks, done, tests): `project/plans/gitops-operator.md`. ADRs 0031 and 0032 are updated to match.

- **Step 2.** Client is `nexus/client/nexus_client/`: `http.py` (was `app/utils.py`), `api.py` (`BackendAPI` + `FncliBackendAPI` merged), `models/`, `git_uri.py`. Tilt's Dagster build needs `custom_build` for the named context: do that first.
- **Step 3.** Group `fn.aridhia.com/v1alpha1`. Kinds `GitProvider`, `NodeSecret` (not `Secret`), `Repository`, `Dataset`, `Project`; category `fn`. CRDs are templates with `resource-policy: keep`.
- **Step 4.** One sync function per kind, also on a 60s timer. The operator reads the source Secret and sends values (nexus-api stores them). Finalizer `fn.aridhia.com/nexus-sync`; a pre-delete hook strips it on uninstall. Login is a Keycloak user `fn-operator` with Administrator, not `System`. nexus-api has no audit record: attribution is Events and git.
- **Step 5.** `fncli apply` also did Gitea repos and OAuth apps: that becomes `fncli gitea setup`, which writes a Kubernetes Secret a `NodeSecret` names. Experiments ship their `Dataset` in `experiments/chart`.
- **Steps 6-9.** Gitea is the chart's own templates. Actions via `GITEA__actions__ENABLED`, runner with a DinD sidecar (dev only). Release publishes to the kind registry. Flux adopts the release `mise run deploy` made; `mise run flux up|down`.

## Next step
1. **Rerun the advisor (Fable, background).** It was cut off by an account switch before writing anything. Its job:
   - Write `project/plans/gitops-operator.md`, the detailed plan. For each step: what and why, real file paths, design decisions, risks, what done means, how to test it.
   - Update ADR 0031: delivery is proved locally first with Gitea, Gitea Actions, `act_runner` and Flux in kind; GitHub Actions comes after.
   - Update ADR 0032 with anything that reading the code forces: CRD group, finalizers, what goes into nexus-client.
   - Fill "Refined plan" above, and list at most 4 open questions for the user.
   - Keep it MADR, terse, no client names, no mention of 0033.
2. Commit and push the advisor's output, then ask codepint the open questions.
3. Step 2 (move the client to `nexus/client/`): Opus lead, with Sonnet doing the import moves.

## Team and permissions
- Fable: advisor; it plans and reviews each step's diff before commit. Opus: dev work, operator then Flux. Sonnet: grunt work. Haiku: basic actions (see AGENTS.md "Agent team"). The main session coordinates, commits and pushes.
- codepint has given this work full control of the dev cluster and permission to push branches. Commit and push after each chunk.
- Run single test files, not full suites. Check `$CLAUDE_CONFIG_DIR/usage.json` before each step.

## Open questions
(Working on the recommended answers below until codepint says otherwise, 2026-11-15.)
- CRD API group: `fn.aridhia.com`? (recommended: yes)
- Operator login: Keycloak user with Administrator now, client credentials later? (recommended: yes)
- A removal nexus-api refuses: hold the resource `Terminating`, or let it go? (recommended: hold)
- Local OCI registry: the kind registry, or Gitea's package registry? (recommended: kind registry)

## State 2026-11-15 (late afternoon)
- Stacked draft PRs into `feat/gitops-operator`, each in its own sibling worktree: #654 CRDs (`gitops-crds`, done, tests pass, review owed), #655 Gitea Actions (`gitops-gitea-actions`, Sonnet working), #656 operator (`gitops-nexus-operator`, Opus working, based on the client move).
- Step 2 reviewed (Fable, comment on #653); its one finding is fixed in 7ee6ca0f0.
- Next: review #654 (Opus), merge #654 into feat/gitops-operator, rebase #656 on it; then #655 and #656 when their agents finish. At the end only `feat/gitops-operator` (#653) remains; delete merged branches and worktrees.
- Update: #656 operator done (6 commits pushed, package `nexus/operator/nexus_operator/`, tests pass). Check its assumed CRD spec/status fields against #654 before merging (status needs `sourceVersions`). Left: operator CI + pylint task, image build, cluster check.
- #655 Gitea Actions done but commit e0edcdd3c is NOT pushed: the agent's push was refused; waiting on codepint's OK to push it.
- Stopped at 95% of the 5h limit.

## State 2026-11-15 (evening)
- Merged into feat/gitops-operator: #654 CRDs, #655 Gitea Actions, #656 operator, #657 release + Flux; all review findings fixed (threads replied). Chart tests 213/213.
- Running at stop: step 5 on #658 (`gitops-dev-apply` worktree, Opus). Merge it when done, then review it.
- Steps 7-9 are written but never run: the dev cluster is owned by `feat/proxy-ca` (claimed 16:10). Next: get the cluster, `mise run deploy` from this worktree, check the operator syncs, a hello-world Gitea workflow, then `mise run flux up` and the loop in `docs/versions/2.x/docs/GitOps-Delivery.md`.
- Known gap outside this work: Dagster's Keycloak password is env, so rotation needs a restart.
- Stopped at 93% of the 5h limit.
