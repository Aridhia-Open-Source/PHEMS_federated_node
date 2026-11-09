# Docs and tooling clean-up plan

Agreed 2026-11-09, from the audit of docs, make targets, scripts and fncli. Branch `docs-tooling-cleanup`,
based on `fncli-bootstrap-files` (#617). Each step is a small PR. Delete this file when the last one lands.

Rule for every step: grep for references first (`git grep -n NAME`), remove or fix them in the same PR.

## Already done (2026-11-09)

- [x] Dead Gitea trigger-simulation scripts, `dev_secrets_env.sh`, `import_microk8s.sh` removed (#617, #613)
- [x] ADR 0027 says `bootstrap/context.yaml`
- [x] `make experiments up` renamed `deploy`; `make deploy` installs the experiments release
- [x] `cluster.sh down` wipes `~/.fn/data` and checks the cluster owner; cluster name comes from `context.yaml`
- [ ] (in progress) fncli connection and `TEST_*` settings move from `.dev.env` to `context.yaml` + node files

## Keep (decided, don't cut)

- `CHANGELOG.md`
- `make portfwd` / `scripts/portfwd.sh` (fallback when Tilt isn't running)
- `make reload_app` / `scripts/reload_app.sh` (not used by Tilt, but keep unless it proves dead)
- ADRs, `docs/architecture/` (incl. sensor flow charts), `docs/schemas/`
- `SETUP_GIT_APPS.md` as the one copy of the GitHub App steps
- Scripts: deploy, teardown, cluster, upgrade, nuke, deploy_owner, new-worktree, bake_files, lint
- `make deploy-owner`, `make worktree`, `show-db-passwords`, `helm_*`, `pylint*`, `hadolint`, `tests_dagster`, `images*`

## 1. Delete dead docs

- [ ] `project/AUTH_BETA.md` (Flask era)
- [ ] `dagster/fncli/DESIGN-node-file.md` (ADRs 0025/0027 cover it)
- [ ] `dagster/fncli/PLAN-experiment-bootstrap.md` (ADR 0028 is the record)
- [ ] `dagster/fncli/tests/e2e/PLAN-e2e-on-bootstrap.md` (turn open items into issues first)
- [ ] `dagster/fncli/EXAMPLES.md` (a fourth walkthrough)
- [ ] `.kind/README.md`, `.kind/main.sh`
- [ ] `dev.k8s/` (only `run_local.sh` used it)
- [ ] `dagster/README.md` (empty) or write 10 lines
- [ ] `paper/` moves out of the repo

## 2. Delete dead commands

- [ ] `make run_local` + `scripts/run_local.sh`
- [ ] `make dashboard`, `make chart`
- [ ] `make tilt-up/down/logs/open` (one-word wrappers; docs say `tilt up`)
- [ ] `scripts/compile.sh` (older copy of `pip_compile.sh`, which `make pip_compile` uses)
- [ ] `scripts/e2e_shared_resources.sh`, `scripts/e2e_check.py` + the nexus test that imports it
- [ ] `scripts/nexus_login.sh`: make it `make login` or delete

## 3. Makefile catch-all

The `%: @:` rule and `up down: @:` let `make cluster up` read `up` as a word, but they also make any typo
(`make deploi`) exit 0 and do nothing.
- [ ] Replace positional words with real targets: `cluster-up`, `cluster-down`, `pip-compile DIR=...`
- [ ] `make experiments X` -> call `fncli experiment X` directly in the docs, drop the make wrapper
- [ ] Remove the catch-all; add a real `make help`

## 4. One way to start

- [ ] `make up` = `helm upgrade --install` (merges `deploy` and `upgrade`; rerun-safe)
- [ ] `make init` copies `.dev.env`, `dev.values.yaml`, `bootstrap/context.yaml` if missing, asks for email + password
- [ ] `make demo` = experiments deploy/seed/setup, start sensors, apply globals + project, `fncli demo`
- [ ] Tilt starts the Dagster sensors (a `local_resource`), so no manual `start-sensor` after deploys

## 5. Tidy fncli

- [ ] Group sensors: `fncli sensors start|stop|status`
- [ ] Group state/verify: `fncli project show|set|healthcheck`, `fncli verify project|repo|git-secret`
- [ ] Hide the step commands (`open-pr`, `create-gitea-branch`, `commit-gitea-file`, `create-gitea-pr`,
      `merge-gitea-pr`, `merge-results-pr`, `delete-gitea-token`): `trigger --pr --merge --watch` replaces them
- [ ] Hide or move to tests: `simulate-setup/run/check/teardown`
- [ ] Delete `hello-world`
- [ ] Hide `trigger --api` until built; label `delete --all` as dev-only in `--help`
- [ ] `./fncli` shim (`uv run`) so a stale pipx install can't run another checkout's code

## 6. Merge duplicate docs

- [ ] One run-locally page from `FRESH_SETUP.md` + `DEMO.md` + local half of `DEPLOYMENT.md` + wiki Run-Locally
- [ ] Production half of `DEPLOYMENT.md` -> the Deploy page only
- [ ] `MANAGEMENT.md` -> Set up a project + Operations, then delete
- [ ] GitHub App steps only in `SETUP_GIT_APPS.md`; delete the other 3 copies
- [ ] `.tilt/` three docs -> one ~100-line page
- [ ] One ADR index (`project/decisions/README.md`); fold `docs/README.md` in; fix broken refs in 0017, 0023, 0024
- [ ] `experiments/UC1_README.md` -> `experiments/README.md`
- [ ] `dagster/fncli/README.md` cut to ~100 lines; command reference generated from click
- [ ] `project/TESTING.md`: drop per-file counts; `project/QA/`: trim "never run" cases
- [ ] Fix the e2e README's `FNCLI_ADMIN_*` preflight instead of noting it in 4 places

## 7. README as the front door

- [ ] Rewrite `README.md` to under 40 lines: what it is, then one link per audience (operator, admin,
      researcher, contributor). No dead wiki pointers.

## 8. Docs home (decide)

- [ ] Decide: repo `docs/` published with MkDocs Material (audit's pick, retires the wiki and #614's sync) or keep the wiki
- [ ] `helm-docs` generates the chart's values reference (replaces `k8s/federated-node/README.md`)
- [ ] Operator install via `helm install oci://ghcr.io/aridhia-open-source/charts/federated-node`

## Open questions

- `fncli apply` as the supported setup on real nodes (today 14 curl calls)
- Wiki: fresh install only, no 1.x -> 2.x upgrade path?
- `extra_connection_args` never reaches the task's `CONNECTION_STRING` (likely bug)

Full audit: `CLEANUP_AUDIT.md` (delete with this file).

## Order (agreed 2026-11-09)

1. Fix the make commands (steps 2 and 3: dead targets, catch-all, real targets, `make help`).
2. Tidy the docs (steps 1, 6, 7).
3. Then mise: a `mise.toml` pinning kind, kubectl, helm, tilt, uv, python; consider mise tasks
   (or `just`) replacing make. The user dislikes make, so this is the end goal.
4. fncli tidy (step 5) and one-command start (step 4) can go alongside.
