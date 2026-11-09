# Docs and tooling audit, 2026-11-09

Read-only audit. Code: `wt-fncli-config` (branch `fncli-declarative-config`, HEAD 8c7f5900). Wiki: `fn-worktrees/wiki-beta` (beta at be7a22d, not yet on the live wiki). Commands checked with `--help` and `make -n` only. Nothing was edited, and the cluster was not touched.

## Summary

- The README is a broken front door. Its two wiki pointers (`How-to-deploy`, `Run-Locally`) do not exist on the live wiki (master has only the 18 old 1.x pages). It still shows the 1.x `/results` flow table and never mentions FRESH_SETUP, DEPLOYMENT, MANAGEMENT or DEMO.
- The same content lives in 3 or 4 places, and each copy says another copy wins. The copies have already drifted.
- 94 markdown files in the repo (9,892 lines) plus 31 wiki pages (4,894 lines). Roughly 40% of the lines are copies, plans, drafts, research, or a manual QA plan that has never run.
- `fncli --help` lists 30 flat commands. 20 are test plumbing. The only supported path to set up a project on a real node is 14 hand-written `curl` calls.
- The `%:` catch-all in the Makefile makes every typo exit 0, and there is no `make help`. A contributor's first run is about 28 commands, 8 tools and 3 config files.
- The 2.x wiki pages point at 18 repo files on `blob/beta/...`. 15 of them are not on the code repo's `beta` branch (it is the old DuckDB-era branch). They 404 until the landing plan puts them there.

Two decisions are needed from you. Everything else is plain clean-up. They are at the end of section 5.

## 1. Inventory

Verdicts: keep, merge into X, move, delete. Line counts are rough. ADRs, QA, sensors and the 1.x wiki are grouped, with only the exceptions broken out.

### Entry points and root docs

| Path | Audience | Lines | Verdict | Reason |
|---|---|---|---|---|
| `README.md` | everyone | 96 | rewrite to under 40 lines | Dead wiki pointers. 1.x flow table. `scripts/pip-compile.sh` is really `pip_compile.sh`. Dependency and lint notes belong in CONTRIBUTING. |
| `FRESH_SETUP.md` | contributor | 439 | merge into one run-locally page | 6 `TODO(verify)`. Copy of DEMO and wiki Run-Locally. Own troubleshooting table. Its intro lists five other docs as the source of truth. |
| `DEMO.md` | contributor | 79 | merge into the same page | Drifted: uses `fncli apply -f experiments/demo/dataset.yaml`, the others use `make experiments setup demo`. Has an uncommitted edit. |
| `DEPLOYMENT.md` | operator, contributor | 419 | split: production half to the Deploy page, local half to run-locally | Production half is word for word the wiki Deploy-Core. Local half is a third first-run walkthrough. Authority is circular: it says the wiki loses, the wiki says this loses. |
| `MANAGEMENT.md` | admin | 384 | merge into Set up a project and Operate, then delete | API section equals wiki Set-Up-A-Project. fncli section is the third copy of the command table. Teaches static `TOKEN` secrets while the wiki teaches GitHub App. Says its commands "have not been run against a live node". |
| `SETUP_GIT_APPS.md` | operator, admin | 43 | keep as the one copy, move to docs as "Connect a git host" | GitHub App steps exist 4 times (this, FRESH_SETUP 9, wiki Run-Locally 8, wiki Set-Up-A-Project). Delete the other 3. |
| `CHANGELOG.md` | all | 337 | delete, use GitHub Releases | Stops at 1.17.0. Chart is 2.0.0. The PR template still asks for it. |
| `.dev.env.example` | contributor | 125 | trim | 9 `TEST_*` lines exist only for the e2e suites and the env-reading fncli commands. |

### Dev tooling docs

| Path | Lines | Verdict | Reason |
|---|---|---|---|
| `.tilt/TILT.md`, `TILT_QUICKSTART.md`, `TILT_SETUP_SUMMARY.md` | 351 / 148 / 237 | merge into one page of about 100 lines | Three docs for one `tilt up`. The SUMMARY is "What is this / the old way / the new way" with an ASCII diagram. `tilt up`, `tilt up --stream` and `make tilt-up` all appear. |
| `.kind/README.md`, `.kind/main.sh` | 43 | delete | README says `kind create cluster --config kind-config.yaml -n fn` and installs kubectl under a "Install kind" comment. The repo uses `make cluster up`. Nothing references `main.sh`. |
| `dev.k8s/` (README + 5 yaml) | 22 | delete | Only `scripts/run_local.sh` uses it, and that is microk8s and dead. |
| `dagster/fncli/README.md` | 285 | keep, cut to about 100 | Pipx install and uninstall essay (also uninstalls pipx itself). Command tables duplicated in 2 other docs. Replace with a reference generated from click. |
| `dagster/fncli/EXAMPLES.md` | 164 | delete | A fourth "from scratch" walkthrough. |
| `dagster/fncli/DESIGN-node-file.md` | 238 | delete | "Draft, design only". Uses `node.yaml`, which became `context.yaml` plus globals and project files. ADR 0025 and 0027 cover it. |
| `dagster/fncli/PLAN-experiment-bootstrap.md` | 46 | delete | Says "Not started", with a banner saying the layout has since changed. ADR 0028 is the record. |
| `dagster/fncli/tests/e2e/PLAN-e2e-on-bootstrap.md` | 196 | delete or turn into issues | "Nothing here has been run." |
| `dagster/fncli/tests/e2e/README.md` | 66 | keep, fix | Preflight names `FNCLI_ADMIN_USER` and `FNCLI_ADMIN_PASSWORD`, which no code reads. TESTING.md and known-issues.md note this error instead of fixing it. |
| `dagster/README.md` | 0 | delete, or write 10 lines | Empty file. `docs/README.md` points to it. |
| `experiments/README.md` | 113 | keep, trim | The wiki Experiments page is a copy. Delete the wiki copy. |
| `experiments/UC1_README.md` | 80 | merge into `experiments/README.md` | Says `projects/uc1/` (now `experiments/uc1/`). Repeats the "Run UC1" section. |
| `nexus/ui/README.md` | 34 | keep | Only covers screenshots. Add how to run the UI. |
| `build/*/README.md` (alpine 12, kc-init 2, keycloak 27) | | keep | `build/keycloak/README.md` points to a missing `cache-ispn.xml`. kc-init is one line. |
| `k8s/federated-node/README.md` | 89 | replace with helm-docs output | Hand-kept, partial values table. The prose ("Existing secrets") moves into the template. |
| `paper/` | 302 | move out of the repo | JOSS paper on 1.x. Not docs. |
| `.github` templates | | keep, edit | PR template ticks "Updated Changelog.md", which is dead. |

### Reviewer and contributor docs (`docs/`, `project/`)

| Path | Lines | Verdict | Reason |
|---|---|---|---|
| `docs/README.md` | 73 | merge into `project/decisions/README.md` | Second ADR index. The two already differ. Points to a missing `auth-mvp-plan.md`. |
| `docs/architecture/` (entities, flows, revoke-and-enabled) | 623 | keep | Mermaid, close to the code. |
| `docs/architecture/sensors/` (10 files) | 803 | keep | One file per sensor with a flow chart. Part overlaps ADR 0014 and 0015. Do not extend. |
| `docs/schemas/*.json` | | keep | Publish at a stable URL so editors can use `$schema`. |
| `project/decisions/` (30 ADRs + index) | 1,286 | keep | Short, structured. Fix 3 broken references: 0017 to `auth-mvp-plan.md`, 0023 to `nexus/api/CONTRACT.md`, 0024 to the old name `0021-webserver-...`. The index lists 0024 before 0023. |
| `project/QA/` (17 files) | 2,327 | keep, trim | Manual plan. About 25 mentions of "never run". Pinned to commit 6c46e803 on `moonshot/shared-resources`. Each case has 6 fields and 2 checkboxes. Merge `known-issues.md` into `revoke-and-enabled.md#known-limits`. |
| `project/TESTING.md` | 235 | keep, cut | Per-file test counts rot at once. Points to a missing `TEST_PLAN.md`. |
| `project/AUTH_BETA.md` | 221 | delete | Flask-era research. `g.caller_is_admin`, `auth(scope)` and `before_request` are not in `nexus/api/app`. Gap labels G1 to G11. |

### Wiki, 2.x pages (beta branch, 1,925 lines). Judged by the same standard.

| Page | Lines | Verdict | Reason |
|---|---|---|---|
| Home | 61 | keep | Good "where to start" by audience. |
| Prerequisites | 93 | merge into Deploy | |
| Deploy-Core | 244 | merge into Deploy, one copy only | Copy of DEPLOYMENT.md production half. |
| Post-Deploy-Testing | 96 | merge into Deploy ("Check it") | |
| Architecture | 118 | keep | |
| Run-Locally | 280 | delete, point to the repo page | Copy of FRESH_SETUP plus DEMO. It says "the repo wins where they differ". |
| Set-Up-A-Project | 220 | keep, rewrite around `fncli apply` | 14 `curl` calls. API version goes in an appendix. |
| Datasets | 89 | merge into Set-Up-A-Project | |
| Researcher-Guide | 113 | keep | Best page in the set. |
| Analytics-Container-Development | 159 | keep | |
| Operations | 97 | keep | |
| Using-The-API | 114 | cut to about 30 lines | nexus-api serves its own `/docs`. |
| Using-fncli | 153 | merge into the generated fncli reference | Third copy of the command table. |
| Experiments | 88 | move to the repo (contributor only) | Copy of `experiments/README.md`. |
| `_Plan-fncli-bootstrap` | 120 | delete before publishing | A plan. Must not reach master: a file there becomes a public page. |

### Wiki, 1.x pages (17 pages, 2,969 lines)

Archive as a frozen 1.x version. Two exceptions. The Azure, AWS, GCP and on-prem pages (744 lines) are the only place for storage, ingress and TLS, and the 2.x docs send operators there ("take only their storage, ingress and TLS parts") even though they describe the Task Controller. Distil them into one "Platform notes" page, then archive. Delete `1.x-Helm-Values-Reference`: helm-docs replaces it.

### Patterns to remove from every doc

- `TODO(verify)` and "has not been run": a guide that says its commands were never tried. Run it once, then delete the hedge.
- Docs that record their own bugs (the `FNCLI_ADMIN_*` mix-up in 4 places) instead of fixing them.
- Plans and drafts kept as docs, with a banner saying what changed since.
- "Source of truth" notes between copies. One copy, no note.
- Per-file test counts, commit hashes and branch names in prose.
- Internal labels (G1 to G11) and ASCII banners.

## 2. Command surface

### make (30 targets)

| Target | Verdict | Why |
|---|---|---|
| `run_local`, `dashboard` | delete | microk8s, 1.x. `run_local.sh` has `[[ ! microk8s ]]`, which is never true. |
| `chart` | delete | No references. CI packages the chart with the shared workflow. |
| `reload_app` | delete | Close to `image-reload` (builds two images, restarts Dagster). Tilt does it live. |
| `portfwd` | delete | Hard-codes `-n fn` and `fn-dev-...`. No Gitea. The Tiltfile has its own copy. |
| `tilt-up/down/logs/open` | delete | One-word wrappers. The docs mix `tilt up`, `tilt up --stream` and `make tilt-up`. |
| `%:` catch-all, `up down: @:` | delete | `make deploi` and `make help` exit 0 and print nothing (checked with `make -n`). Add a real `help`. |
| `cluster up\|down`, `experiments ...`, `pip_compile DIR` | replace | They read positional words through the catch-all. Use `cluster-up`, `cluster-down`. For experiments, call `fncli experiment ...` directly: `--local` already needs that. |
| `deploy` and `upgrade` | merge | `deploy` runs `helm install`, so a rerun fails. `upgrade` skips image builds and secrets. One idempotent `make up`: `helm upgrade --install`. |
| `deploy-owner`, `worktree` | keep | Multi-worktree glue. Document in CONTRIBUTING only. |
| `show-db-passwords`, `helm_*`, `pylint*`, `hadolint`, `tests_dagster`, `images*` | keep | CI or daily use. |

### scripts/

| Script | Verdict | Why |
|---|---|---|
| `compile.sh` | delete | No reference. `pip_compile.sh` is the one the Makefile calls. |
| `run_local.sh`, `portfwd.sh`, `reload_app.sh` | delete | See above. |
| `nexus_login.sh` | decide | Only an ADR rename table mentions it. Make it `make login` or delete. |
| `semver_bump.py` | check, then delete | No reference in this repo. The release workflow lives in the shared pipelines repo: look there first. |
| `e2e_shared_resources.sh`, `e2e_check.py` | delete with one test | TESTING.md calls them "an older shell run". `nexus/api/tests/test_live_client_integration.py` still imports `e2e_check`. |
| `deploy.sh`, `teardown.sh`, `cluster.sh`, `upgrade.sh`, `nuke.sh`, `deploy_owner.sh`, `new-worktree.sh`, `gateway-api-installer.sh`, `bake_files.sh`, `tilt_manifests.py`, `upgrade_subchart.py`, lint scripts | keep | In use. |

### fncli (30 commands, flat)

| Group | Commands | Verdict |
|---|---|---|
| The product (6) | `apply`, `diff`, `delete`, `demo`, `trigger`, `experiment` (7 subcommands) | Keep at top level. |
| Sensors (3) | `start-sensor`, `stop-sensor`, `sensor-status` | Group as `sensors start\|stop\|status`. Naming is verb-noun and noun-verb mixed. |
| State and verify (9) | `project-show`, `project-set`, `project-healthcheck`, `resource-set`, `global-set`, `secret-set`, `verify-project`, `verify-repo`, `verify-git-secret` | e2e helpers with `--expect`. Group `project show\|set\|health`, hide the rest. |
| Step commands (7) | `open-pr`, `create-gitea-branch`, `commit-gitea-file`, `create-gitea-pr`, `merge-gitea-pr`, `merge-results-pr`, `delete-gitea-token` | Test internals. Hide. A user has `trigger --pr --merge --watch`. |
| Simulation (4) | `simulate-setup/run/check/teardown` | "Has not been run". Hide or move to a test. |
| Other (1) | `hello-world` | Delete. `fncli --version` is enough. |

Confusing in `--help`:

- Two rules for the default project. `trigger` and `demo` use `defaults.project` from the context file. `verify-git-secret`, `project-set`, `resource-set` and others use `TEST_PROJECT_NAME` from `.dev.env`.
- `trigger --api` says "Not built yet".
- Three ways to open a pull request: `trigger --pr`, `open-pr`, and the 4 step commands.
- `delete` says nothing is forced. `delete --all` is dev-only but is not labelled so in `--help`.

### Things a user must run that should be one command

| Today | Should be |
|---|---|
| `make helm_deps`, `make cluster up`, `make deploy` | `make up` |
| `pipx install -e` per checkout (a stale one gives "No module named fncli"; the fix is repeated in 6 docs) | `./fncli` shim that runs the checkout's own code (`uv run`) |
| `cp` three files (`.dev.env`, `dev.values.yaml`, `bootstrap/context.yaml`), then edit | `make init` copies what is missing and asks for email and password |
| `make experiments up`, `seed demo`, `setup demo`, then `start-sensor --group all`, `apply` twice, `demo` | `make demo`. The order matters: setup must come before the project apply. |
| After every `teardown` or `deploy`: `tilt up`, `start-sensor --group all` again | A Tilt `local_resource` that starts the sensors |
| Operator: clone the repo to run a 2-line CRD script | Put the two `kubectl apply --server-side` URLs in the docs |
| Operator: `helm repo add` + `--devel` | `helm install oci://ghcr.io/aridhia-open-source/charts/federated-node --version X`. CI already pushes it (build.yml). |
| Operator: sensors start stopped, step buried in Operations | One line at the end of the Deploy page and of `fncli apply` output |

## 3. Proposed structure

### Where each audience starts

Repo README has four doors and nothing else: Run it (docs site), Deploy it (docs site), Use it (docs site), Contribute (CONTRIBUTING.md). Each audience lands on one page, not the wiki Home.

| Audience | Starts at | Journey today | Target |
|---|---|---|---|
| Operator | docs site "Deploy" | 6 wiki pages (about 870 lines) plus 744 lines of 1.x platform pages, about 10 helm/kubectl commands, then 14 `curl` to set up a project. Lost at: live wiki is 1.x, Deploy-Core vs DEPLOYMENT.md, `--devel`, release-name rule, sensors, no example values file in the repo. | 3 pages, about 12 commands |
| Project admin | docs site "Set up a project" | 3 docs plus a 4th copy in the fncli README. 14 `curl` with ids carried by hand, or fncli ("dev only"). Lost at: which is supported, static token vs GitHub App. | 1 page, 4 commands |
| Researcher | docs site "Researcher guide" | 2 pages. Fine. Spec rules also in MANAGEMENT, ADR 0002 and the schema. Lost at: no starting template, 4 facts must come from the admin, schema only on a `beta` path that does not exist yet. | 2 pages, plus a template repo |
| Contributor | `CONTRIBUTING.md` | README, FRESH_SETUP, DEMO, DEPLOYMENT (local), 3 Tilt docs, fncli README, EXAMPLES, experiments README: about 10 docs. About 28 commands, 8 tools, 3 files edited, 2 terminals. Lost at: three walkthroughs with different command forms. | 2 docs, 5 commands |

### Target doc set

- Repo root: `README.md` (under 40 lines), `CONTRIBUTING.md` (new, about 100 lines: first run, tests, doc rules), `LICENSE`. Nothing else.
- `docs/` (the source of the published site, plain Markdown, also readable on GitHub):
  - Use: `index`, `architecture`, `deploy`, `git-hosts`, `set-up-a-project`, `operate`, `datasets`, `platform-notes`, `researcher-guide`, `container-guide`.
  - Reference: `helm-values` (generated), `fncli` (generated), `api` (points to `/docs` on the node), `spec.schema.json`, `run.schema.json`.
  - Contribute: `run-locally`, `tilt`, `experiments`, `testing`.
  - Keep: `decisions/` (ADRs, moved from `project/`), `architecture/` (diagrams), `qa/` (trimmed).
- Result: about 14 pages for people, against 128 files today. `project/` and `docs/` become one tree.

### First-run flow per audience (10 steps or fewer)

Operator:
1. Read the prerequisites table at the top of Deploy (cluster with NetworkPolicy, Postgres, ReadWriteMany storage, hostname and TLS, git host).
2. Apply the two CRD sets (two `kubectl apply --server-side` lines).
3. `kubectl create namespace`, then the 2 or 3 secrets (one block).
4. Copy `prod.example.values.yaml`. Set host, `nodeId`, database, storage, first user, domains.
5. `helm upgrade --install ... oci://... --version X -f values.yaml`.
6. `helm test`, then the health check URL.
7. Create the GitHub App or Gitea OAuth app (Connect a git host).
8. Set up the first project (the admin flow below).
9. Start the sensors.
10. Sign in at `https://host/nexus-ui/`.

Project admin:
1. Write the context file for the node (url, admin login).
2. Write `globals.yaml` and `project.yaml` (copy the examples).
3. `fncli diff -f globals.yaml`
4. `fncli apply -f globals.yaml`
5. `fncli apply -f project.yaml`
6. `fncli sensors start` and check the project in the UI.

Researcher:
1. Ask the admin for: trigger repository, watch directory, base branch, dataset name.
2. Create a repo from the template (Dockerfile, analysis script, example spec, build action).
3. Write the analysis. Read the env contract in the container guide.
4. Build and push the image.
5. Write `spec.json` with `$schema` set, so the editor checks it.
6. Open a pull request into the trigger repository and ask for a merge.
7. Wait for the task (the guide says how long and what the states mean).
8. Review the results pull request.

Contributor:
1. `git clone`, `mise install` (kubectl, helm, kind, tilt, jq, uv, python pinned).
2. `make init` (copies the 3 config files, asks for email and password).
3. `make up` (cluster, images, chart; rerun-safe).
4. `tilt up` in a second terminal.
5. `make demo` (demo database, sensors, apply, guided pull request walk).
6. `make nuke` to start again. Optional: `make demo-github` after Connect a git host.

## 4. Existing tools that could replace custom glue

Two constraints shape this section.

- gh-pages already serves the Helm repo `index.yaml`, written by the shared `helm-build.yml`. Pages has one source, so a docs site must share it. `mike` can deploy into a subfolder (`--prefix`), but test that on a fork first.
- The GitHub wiki takes no pull requests and shows only master. The beta pages are invisible today and cannot be reviewed. Unreviewed AI text is the problem you described, so the source should live in the repo.

| Tool | Replaces | Effort | Verdict |
|---|---|---|---|
| MkDocs Material + mike + mkdocs-click | The wiki, the `1.x-` filename prefixes, the sync script from the earlier plan, the hand-kept fncli tables. Gives search, versions, and `mkdocs build --strict` as a broken-reference check in CI. | 2 to 3 days (move about 14 pages, nav, workflow, fork test of gh-pages) | Yes, recommended 1. If the gh-pages sharing is blocked, keep the wiki as the shown site and sync it from `docs/` by CI. |
| mise (with uv) | `curl \| bash` installers in FRESH_SETUP 2, the "pins no version" `TODO(verify)`, the per-checkout `pipx install -e`, `.dev.env` loading. | 0.5 day (`mise.toml`, plus a `./fncli` shim via `uv run`) | Yes, recommended 2. Keep make as the task runner. |
| helm-docs | The hand-kept chart README table, `1.x-Helm-Values-Reference`, "there is no 2.x values reference page yet". | 0.5 to 1 day (add `# --` to existing comments; `values.schema.json` already exists) | Yes, recommended 3. |
| Docusaurus | Same as MkDocs | 3 to 5 days, JS toolchain | No. |
| `helm install` with a values wizard | First values file | Medium | No. Commit `k8s/federated-node/prod.example.values.yaml` and render it in CI (`helm_template`). The schema already validates it. |
| devcontainer | Tool installs | Medium to large | No. Registries on `localhost:5001-5003` and kind inside Docker on WSL2 make networking harder than the problem. |
| Tilt alone, no make or scripts | `deploy.sh`, `upgrade.sh`, `reload_app.sh`, `portfwd.sh` | Large | No. The chart relies on install-time `lookup` and hooks that `helm template` cannot do. Use Tilt `local_resource` buttons for sensors and demo only. |
| just | Makefile | Small | No. Swaps one runner for another. Add `make help`. |
| Backstage-style templates | Researcher starting point | Large | No. A plain GitHub template repository does the job (see plan 12). |
| `gh` extension for fncli | fncli | Medium | No. fncli also targets Gitea, which `gh` cannot reach. |

## 5. Clean-up plan

One pull request per step. Each is mergeable alone. Sizes: S under half a day, M one to two days, L more.

1. **Delete the dead docs (S).** `TILT_SETUP_SUMMARY.md`, `DESIGN-node-file.md`, `PLAN-experiment-bootstrap.md`, `PLAN-e2e-on-bootstrap.md`, `AUTH_BETA.md`, `.kind/README.md` and `.kind/main.sh` (keep the two yaml files: `cluster.sh` uses them), `dev.k8s/`, the empty `dagster/README.md`. Merge `UC1_README.md` into `experiments/README.md`. Fix the 6 broken references. Fix `FNCLI_ADMIN_*` in the e2e README and drop the notes about it in TESTING.md and known-issues.md. Fix the README's two dead pointers and its `pip-compile.sh` name.
2. **Make cleanup (S).** Delete `run_local`, `dashboard`, `chart`, `reload_app`, `portfwd`, `tilt-*` and `scripts/compile.sh`, `run_local.sh`, `portfwd.sh`, `reload_app.sh`. Remove `%:` and add `help`. This breaks `make cluster up` and `make experiments ...`, so in the same PR: `cluster-up`, `cluster-down`, and docs call `fncli experiment ...`. Update every doc that shows the old forms.
3. **`make up` (S).** `deploy.sh` uses `helm upgrade --install`, so a rerun works. Fold `upgrade` into it. Keep `deploy` as an alias for one release.
4. **fncli surface (M).** Hide the 7 step commands, 4 simulate commands and `hello-world` (`hidden=True`). One default-project rule: the context file everywhere. Group sensors and project commands. Add the `./fncli` shim.
5. **Production example values (S).** Commit `prod.example.values.yaml`, render it in `helm_template`, and replace the two inline copies (DEPLOYMENT.md and wiki Deploy-Core) with a pointer.
6. **One run-locally doc plus CONTRIBUTING (M).** Merge FRESH_SETUP, DEMO and the local half of DEPLOYMENT into `docs/run-locally.md`. Do one real run on a clean machine, then remove every `TODO(verify)`. Merge the 3 Tilt docs into `docs/tilt.md`. Write CONTRIBUTING.
7. **One operator doc (M).** Make Deploy the only copy of Deploy-Core and the DEPLOYMENT.md production half. Use OCI in the commands. Add the two CRD lines. Distil the 4 platform pages into Platform notes.
8. **Docs into the repo with MkDocs Material (M to L).** Move the 2.x wiki pages (after steps 6 and 7) into `docs/`. Use repo-relative paths, not `blob/beta/...`. Set up mike and `mkdocs build --strict`. Archive 1.x as a version. Retire the wiki to a one-page "moved" note. Do not publish the wiki beta branch to master before this, and delete `_Plan-fncli-bootstrap` first.
9. **helm-docs (S to M).** Generate the chart README and `helm-values.md`. Delete `1.x-Helm-Values-Reference`.
10. **mise (S).** `mise.toml` pinning kubectl, helm, kind, tilt, jq, uv and python. Delete the installer sections.
11. **`make init` and `make demo` (S to M).** `init` copies the 3 files and prompts for the login. `demo` runs experiments up, seed, setup, sensors, apply twice and the guided walk. Add a Tilt `local_resource` that starts the sensors.
12. **Researcher template repository (S to M).** `phems-task-template`: Dockerfile, analysis script, example spec with `$schema`, a build-and-push workflow. Source: `experiments/demo/image/`.
13. **Changelog (S).** Switch to GitHub Releases. Remove the PR template tick. Delete `CHANGELOG.md`.
14. **Trim the QA plan and TESTING.md (M).** Remove commit and branch pins, test counts and "never run" notes. Merge `known-issues.md`. Fix the 3 ADR references and the index order, and merge `docs/README.md` into the ADR index.

### Decisions needed from you

- **Where the docs live.** Recommendation: in the repo under `docs/`, published with MkDocs Material, and the wiki retired. The alternative (keep the wiki, sync from the repo) is cheaper now and worse for reviewing and versions.
- **Is `fncli apply` the supported way to set up a project on a real node?** Recommendation: yes. It is declarative, diff-first, additive, and never prints a secret. Today it is labelled dev-only because it logs in through the `keycloak-first-user` secret in the cluster and ships inside the Dagster package. Making it real needs a login by env var or prompt, and a package an admin can install without a checkout. That is a code change (L), separate from this clean-up. Until it is done, the admin page keeps the API steps as an appendix.
