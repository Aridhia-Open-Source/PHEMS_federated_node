# verify/all report (2026-11-24)

Branch: dagster-develop + operator top (feat/operator-grants: ci, refactor, auth, operator) + flux top
(feat/flux-remove-copy-secrets), rebuilt by `scripts/verify_branch.sh`. Fresh `mise run teardown` + `mise run deploy`
on kind `fn`, `operator.enabled: true`, Gitea on, then `mise run flux publish 0.0.1-dev` + `mise run flux up`.

| What | Result |
|---|---|
| Deploy (plain Helm) | yes: nexus-api, UI, Dagster, Gitea, Keycloak, operator all Running |
| Operator applies config | yes: datasets + NodeSecrets (experiments), GitProvider, NodeSecrets, repositories, project (config/gitea.yaml, config/demo.yaml) all Synced |
| PR-trigger run, plain Helm | yes: `fncli trigger --pr --merge --watch triggers/examples/demo.json`, 15/15 checks, results PR #1 |
| Flux adopts the release | yes: HelmRelease Ready, chart 0.0.1-dev, revision 2, no reinstall |
| SOPS Secrets via Flux | yes: keycloak-first-user and keycloak-superuser decrypted into keycloak by the fn-site Kustomization |
| PR-trigger run under Flux + operator | yes: 15/15 checks, results PR #2 |
| Change from git (Flux -> chart -> operator) | yes: `nodeConfig.providers: [github]` pushed to fn-site, helm revision 3, GitProvider `github` Synced |

Not run: chart version bump/rollback from the site repository, `flux down`, operator update/delete/turn-off rows, auth role
rows, unit/static suites (CI covers them).

## Merge conflicts (resolved by rule in verify_branch.sh)
CHANGELOG, README, docs/README, ADR index: union. values.schema.json: three-way by key (keeps auth's removal of
`ownerGroups`). copy-secrets.yaml: flux's delete. upgrades_test.yaml, mise.toml, deploy.sh: checked-in files in
`scripts/verify_resolutions/`. No kc-init, openapi.json or schema.d.ts conflict.

## Fixes on verify/all (details and patches: .claude/handover/verify-findings.md)
1. deploy.sh: keycloak-superuser goes in the keycloak namespace (copy-secrets is gone); namespace loop adds fn-operator and experiments.
2. operator-namespace.yaml: off with `global.createNamespaces=false`, else every redeploy is refused.
3. site-example: operator values, superuserSecret, fn-operator namespace, SOPS superuser Secret (flux.sh fills it).
4. kc-init: operator user created with `group="/roles/service"` (was `role_name=`, a TypeError that stopped realm init).
5. Tokens had no `sub` (global client lacked the `basic` scope): realms.json + kc-init migration m004.
6. config/demo.yaml: project grants `/roles/admins` read, so fncli (admin) can find it.
7. portfwd.sh forwards Gitea on 4000.

## Manual steps that are documented, not bugs
`fncli start-sensor --group all` after deploy (sensors start stopped); FN_USERNAME/FN_PASSWORD for fncli.

## State left behind
Flux owns fn-dev on cluster `fn` (claim released). `mise run deploy`/`teardown` refuse elsewhere until
`mise run flux down` runs from `fn-worktrees/verify-all` (it holds the SOPS age key and `.dev.env`).
