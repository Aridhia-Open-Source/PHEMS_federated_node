# Handover: gitops operator (ADR 0032) then Flux (ADR 0031)

Resume: read this file, then `git log --oneline origin/dagster-develop..HEAD`. Worktree: `../gitops-operator`, branch `feat/gitops-operator`, draft PR into `dagster-develop`.

**Goal:** every change to a node, both version and config, goes in as a git commit that can be reviewed and reverted.

## Rules
- Commit and push after each step; update this file in the same commit.
- Unit tests for changed files only. No e2e. No cluster teardown or takeover (`mise run deploy-owner` first).
- No Co-Authored-By lines. Imports at module top. Copy existing patterns; no defensive code.
- Stop at 95% of the 5h usage limit (`~/.claude/usage.json`), push, and update this file.

## Steps
Part 1, operator (ADR 0032):
1. [x] Delete ADR 0033 and its index row.
2. [ ] Move the shared API client from `dagster/app` to `nexus/client/` (own pyproject; path dep compiled with each consumer; bake named context). Dagster and fncli tests pass.
3. [ ] CRDs + `nodeConfig` chart templates, schema, helm-unittest.
4. [ ] Kopf operator in `nexus/operator/`: sync to nexus-api, soft delete, status, Keycloak service client, RBAC, image, Tilt.
5. [ ] Move experiment setup / e2e / demo onto `kubectl apply`; drop fncli `diff/apply/delete`; docs.

Part 2, Flux (ADR 0031), local with Gitea first:
6. [ ] Gitea Actions + `act_runner` in the bundled Gitea (dev only).
7. [ ] Release workflow in Gitea Actions publishes chart + images as OCI.
8. [ ] Flux in kind + test site repo in Gitea (HelmRelease, values, `nodeConfig`); scripted.
9. [ ] Prove the loop: bump, revert, config edit. Doc it.
10. Later, separate PR: GitHub Actions port, release bundle, SOPS, OpenTofu.

## Refined plan
(Filled in by the advisor review.)

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
- Fable: advisor; it plans and reviews each step's diff before commit. Opus: leads, operator then Flux. Sonnet: mechanical work. The main session coordinates, commits and pushes.
- codepint has given this work full control of the dev cluster and permission to push branches. Commit and push after each chunk.
- Run single test files, not full suites. Check `~/.claude/usage.json` before each step.

## Open questions
- CRD API group name (ADR 0032 says `fn.aridhia.com`, to be decided).
