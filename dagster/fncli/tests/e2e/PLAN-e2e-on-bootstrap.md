# Plan: the e2e suites on bootstrap files

Status: plan only, 2026-11-09. Read against `fncli-declarative-config` (b4d68379). Nothing here has been run.
Rule for every step below: never start `--e2e` while one is running (`pgrep -f pytest` first), and only on `kind-fn`.

## Summary

- The suites set up and tear down through `apply` and `delete`. Everything else still reads `TEST_*` from `.dev.env`.
- So two sources describe the same project: the node file and `.dev.env`. The e2e.yaml header says "keep them equal". Nothing checks it.
- Smallest useful slice: batch the six missed-PR checks (tests only, saves about 4.5 min).
- Biggest fix: `--project` on the PR, verify and healthcheck commands, so the project comes from the backend and `TEST_*` goes away.
- New suite for `diff`, `apply`, `delete` (about 5 min, never waits for a sensor), run first so a broken apply fails in minutes, not after 35.

## 1. Inventory

### conftest.py (shared)

- Setup, run as one test each: `apply -f e2e.yaml -y`, `verify-git-secret` for trigger and results, `project-healthcheck`.
- Teardown, in this order: `delete -f e2e-second-projects.yaml -y`, `delete -f e2e.yaml --all -y`, then `delete_gitea_leftovers` (Python: deletes the Gitea repos and OAuth apps the node file names).
- Reads env: `NEXUS_API_URL`, `KEYCLOAK_NAMESPACE` (every backend client), `TEST_PROJECT_NAME` (`Fncli.snapshot`, healthcheck, verify), `NAMESPACE` (Gitea admin password, sensor configmap), `GITEA_URL`, `DAGSTER_URL`.
- Hard-codes `SECOND_PROJECT = "QaTwo"`, a second copy of a name that is in e2e-second-projects.yaml.
- `Fncli.run` prints to the terminal and asserts exit 0. It cannot assert on `diff` text or on an expected exit 1.
- `cli.main(standalone_mode=False)` returns an exit code but raises a `ClickException`, so a refused command needs its own helper.

### test_happy_path.py (19 tests, one PR through a task to a merged results PR)

- Setup and teardown steps from conftest (teardown twice: leftovers, and the final one with `E2E_TEARDOWN=1`).
- Env-based: `create-gitea-branch`, `commit-gitea-file`, `create-gitea-pr`, `merge-gitea-pr` (`PrConfig`: `TEST_TRIGGER_REPO*`, `TEST_PR_IMAGE`), `merge-results-pr` (`TEST_RESULTS_REPO*`), `verify-project` (`TEST_PROJECT_NAME`, `DEFAULT_PROJECT_DATASET`), `verify-repo` (`TEST_TRIGGER_REPO*`).
- Flips nothing.
- Awkward: all the env values above must equal e2e.yaml, silently. An empty one gives an empty repo path, not an error.

### test_failure_paths.py (76 tests, no task runs)

- Preflight: admin login from the `keycloak-first-user` secret.
- Six flip groups, each: record counts, flip, merge a PR, wait 5 ticks, flip back, wait 5 ticks again (the missed-PR check).
  - revoked trigger resource: `resource-set trigger --revoked`
  - revoked project: `project-set --revoked`
  - disabled trigger resource: `resource-set trigger --enabled`
  - disabled global trigger repository: `global-set trigger --enabled`
  - revoked global trigger repository: `global-set trigger --revoked`
  - disabled secret: `secret-set --entity trigger --enabled`, then `global-set trigger --enabled`
- Two PR kinds: `commit-gitea-file --kind invalid`, `--kind unwatched`.
- Concurrent token refresh: `TriggerRepoConfig().repo_uri` and `init_gitea_repo` (both env), k8s secret reads.
- Awkward:
  - `secret-set` builds the label from env (`<TEST_TRIGGER_REPO>-creds`). It matches e2e.yaml only because the names were chosen to match.
  - The six missed-PR waits cost about 4.5 min more than one wait would.
  - A group that leaves a flag flipped is only noticed by the next group.

### test_failure_paths_long.py (64 tests, tasks run to the end)

- Same setup and teardown, same admin preflight.
- Second project: `apply -f e2e-second-projects.yaml --project QaTwo`, `resource-set trigger --revoked --project QaTwo`, `delete -f e2e-second-projects.yaml`.
- Lost token: `delete-gitea-token` (token name from `GITEA_TOKEN_NAME`, default `fn-sensor`), `sensor-status`, `project-healthcheck` (expects exit 1), `apply -f e2e.yaml --rotate <label>`, `verify-git-secret`.
- Failing task: `commit-gitea-file --kind failing`.
- Backfill: `project-set --enabled false`, then `project-set --enabled true --backfill`.
- Work in flight: `resource-set results --enabled`.
- Awkward:
  - `delete-gitea-token` deletes the app named by an env default. It equals `gitea_oauth.app` in e2e.yaml by coincidence.
  - The node file has no say in which Gitea app is deleted.

### Broken or awkward across all of them

- Two sources of truth (node file, `.dev.env`) and two node addresses (node block for apply, `NEXUS_API_URL` for the rest).
- The kube-context check lives only in `diff`, `apply`, `delete`. PR-side and `*-set` commands use whatever context kubectl has.
- `delete` leaves Gitea repos and OAuth apps, so conftest does it by hand.
- e2e-second-projects.yaml repeats all globals (about 35 lines). The comment says "the same name in every file, or applying one renames it for the others". Cross-file references now make the repeat unnecessary.
- A no-op re-apply of a file with a `gitea:` section prints "Applied 2 changes": the Gitea repository rows are always in the to-do list (`to_do` keeps ENSURE).
- README preflight says `FNCLI_ADMIN_USER` / `FNCLI_ADMIN_PASSWORD`. The code reads the `keycloak-first-user` secret (already in project/QA/known-issues.md).
- `--e2e` sets `maxfail=1`: a late failure costs the whole run, so cheap checks should run first.

## 2. Target shape

### Scenario state is files, reached with `apply`

- Baseline: `bootstrap/examples/e2e.yaml`. No new committed file for the baseline.
- Second projects: slim e2e-second-projects.yaml to the node block and the two projects. Its datasets, repositories and secrets resolve from the node (cross-file). Checked: the slim file loads, and against a node without the dev entries it plans one blocked row per project ("dataset dev-dataset is not in the file or on the node").
- Variants: a `variant(base, edit)` helper in conftest. It loads the YAML, edits the dict, writes it to a tmp path. No new committed files. The e2e files hold no relative paths or `env_file`, so a tmp copy is safe.
- If someone adds `node.env_file` to an e2e file: `open_node` calls `load_dotenv(..., override=True)`, which changes `os.environ` for the rest of the pytest process.

### State flips: who owns which flag

- File-owned (flip by editing the file and `apply`): project `enabled`, trigger and results assignment `enabled`, `watch_dir`, `base_branch`, `target_dir`.
- Hand-owned (kept `*-set` commands, the file never sets them): `revoked` at project, resource and global level, global `enabled`, secret `enabled`, `--backfill`.
- Decision: leave the failure-suite flips on `*-set`. Those scenarios test nexus-api rules, not apply, and `apply` cannot set most of the flags anyway. The one file-owned flip in them (disabled trigger resource) is covered once, in the new nodefile suite, where it also checks that apply does not touch `revoked`.
- `apply` is the reset for file-owned flags: after a hand flip of `enabled`, `diff` shows `enabled: false -> true` and `apply` puts it back.

### Teardown is `delete`

- `delete -f second -y`, then `delete -f e2e.yaml --all --gitea -y` (new flag, below). `delete_gitea_leftovers` goes away.
- Both must exit 0. The order stays: second projects first, or the shared globals are refused (409).

### PR-side commands read the project from the backend

- `--project NAME` on the PR, verify and healthcheck commands (gap list below). The repository, branches, directories, results dir and dataset come from the project's assignments.
- `Fncli` gets a `project` attribute and `call()` / `run()` add `project=` for commands that take it. Most test lines stay as they are.
- `PROJECT` and `SECOND_PROJECT` are read from the node files, not typed twice.

### Re-apply and diff as assertions

- `assert_in_sync(file)`: `read_plan(file, None)` returns the changes; every action must be UNCHANGED or ENSURE. Assert on actions, not on text, because ENSURE rows always print.
- Call it after setup and before the final teardown in each suite. The second call catches a group that left a project or assignment flag flipped. About 2 s each.
- In the nodefile suite also assert: backend state before a re-apply equals the state after (`read_state` dataclasses), and the OAuth `CLIENT_SECRET` / `REFRESH_TOKEN` and the generated dataset `USERNAME` / `PASSWORD` in the k8s secrets are unchanged.

### Node-block safety

- The node block (`url`, `kube_context`) is the authority. `diff`, `apply`, `delete` already refuse another context.
- Preflight in the `Fncli` fixture (once per module): `current_context() == node.kube_context`, and `NEXUS_API_URL` and `KEYCLOAK_NAMESPACE` from `.dev.env` equal the node block. This covers every command that does not check itself.
- A test refuses a variant with a wrong `kube_context` and proves the backend is unchanged.
- Later, not now: every backend-using command honours `FNCLI_NODE_FILE` for url and keycloak namespace. It removes the second address, but it is a wider change than the e2e needs.

## 3. fncli gaps and the small change for each

Each is a change in fncli, with its unit test next to the command's existing tests.

- **PR, verify and healthcheck commands need `TEST_*`, no `--project`.** Affects `create-gitea-branch`, `commit-gitea-file`, `create-gitea-pr`, `merge-gitea-pr`, `merge-results-pr`, `verify-repo`, `verify-project`, `project-healthcheck`.
  - Change: add `--project` (and `--repository URI`, needed only when the project has more than one trigger).
  - Reuse `load_repo_config(entity, from_backend=True, project)` in cmds/repository.py. It already does this for `verify-git-secret`. Give it a `config_class` argument so it can build `PrConfig` (keeps `TEST_PR_IMAGE`, `TEST_PR_ENV`, `TEST_PR_TAGS`, `TEST_PR_CONFIG` as options with env defaults, as DESIGN-node-file.md says).
  - `verify-project`: dataset from the project's default dataset, optional `--dataset`.
  - Size: M (8 commands, one shared loader, existing tests in test_pr.py, test_verify.py, test_repository.py).
- **`secret-set` takes its label from env.** Change: `secret-set LABEL --enabled true|false`. The suite passes the label it reads from the node file (`trigger_secret_label()` already exists). Size: S.
- **`delete-gitea-token` takes the app name from `GITEA_TOKEN_NAME`.** Change: `--app NAME`, no env default. The suite passes `secrets[label].gitea_oauth.app` from the node file. Size: S.
- **`delete` leaves Gitea repos and OAuth apps.**
  - Change: `--gitea` (needs `--all` and a `gitea:` section). It adds rows `- gitea repo` and `- gitea oauth app`, last in the order, deleted with `GiteaAdminAPI.delete_repo` and `delete_oauth_app` (both already exist and return False when absent). The prompt lists them, since a Gitea repo with commits is lost.
  - Without the flag the message stays "left in place". Size: S.
- **A no-op re-apply says "Applied 2 changes".** Not blocking (the suite asserts on actions). Change when wanted: `diff` asks Gitea whether each repository exists and shows `=` or `+` instead of `?`. Size: S to M.
- **Other commands skip the kube-context check.** Covered by the e2e preflight above. The wider fix is the `FNCLI_NODE_FILE` idea, later.
- **No test helper to capture output or a refusal.** In conftest, not fncli: `Fncli.output(*args, code=0) -> str` (stdout via `redirect_stdout`), `Fncli.refused(*args) -> str` (catches `ClickException`), `plan(file, project=None) -> list[Change]` (calls `read_plan`). Size: S.
- **Stays as it is on purpose:** `apply --backfill` (not needed, `project-set --backfill` stays), `revoked` and global `enabled` in the file (DESIGN-node-file.md section 6), `TEST_PR_IMAGE` and friends (per-PR inputs).

## 4. New e2e tests for `diff`, `apply`, `delete`

A new file, `test_nodefile.py`, marker `e2e_nodefile`, run with `--e2e nodefile`, ranked before `success`. It needs no running sensors and merges no PR. Edits to dagster/conftest.py: the suite name, the marker, the rank.

Each item is one or a few single-step tests, in order, in the existing style.

- **Fresh apply.** With none of the file's entries on the node (`delete --all --gitea` first; other entries, such as the demo's, are left alone):
  - `diff` exits 0, prints only `+` rows and `?` Gitea rows, and creates nothing (`find_project` is None).
  - `apply -y` exits 0. The project is enabled; one trigger and one results assignment with the file's `watch_dir`, `target_dir`, `base_branch`; the dataset is assigned and is the default.
  - `verify-git-secret` for both repositories and `project-healthcheck` pass (these are today's setup steps).
- **Re-apply is a no-op.**
  - `assert_in_sync` passes.
  - State before equals state after a second `apply -y`.
  - The OAuth secrets and the generated dataset credentials are byte-for-byte unchanged (guards "Gitea OAuth must never run on every apply").
  - The output has no `+` or `~` row.
- **PATCH update keeps `enabled`.**
  - Variant with the trigger `enabled: false`: apply; the assignment is off, the project is on, `active` is false.
  - Variant with the same plus a new `watch_dir`: `diff` shows exactly one `watch_dir` row; apply; the new `watch_dir` is there and `enabled` is still false (a PUT would have set it back to true).
  - Variant with a new results `target_dir`: `diff` carries "earlier tasks will fail"; apply; restore.
  - Baseline apply puts everything back.
- **Apply resets a hand flip, but not `revoked`.**
  - `resource-set trigger --enabled false`: `diff` shows `triggers[...].enabled: false -> true`; apply sets it on.
  - `resource-set trigger --revoked true`: `diff` shows nothing for it; apply leaves it revoked. Restore with `--revoked false`.
- **`--rotate`.**
  - `apply --rotate <trigger label>`: its `CLIENT_SECRET` and `REFRESH_TOKEN` change; `verify-git-secret` passes; the results and dataset secrets are unchanged.
  - `--rotate not-a-label` fails with the label named and the backend unchanged.
- **`delete` without and with `--all`.**
  - Apply the second projects. `delete -f e2e.yaml -y`: the dev project is gone, repositories, dataset, secrets, provider stay, QaTwo and QaThree stay, the Gitea repositories exist. `diff` then shows the project as `+` and the rest unchanged.
  - Without `--gitea`, Gitea repositories and OAuth apps remain after `delete --all`. With `--gitea` they are gone.
  - `delete --all` with none of the file's entries on the node prints "Nothing to delete." and exits 0.
- **409 skip for shared globals.** With the dev project and QaTwo applied: `delete -f e2e.yaml --all -y` exits 1.
  - Output has "Skipped, the backend refused" and names QaTwo.
  - The dev project is gone; the repositories and the dataset are still on the node.
  - Then `delete -f second -y` and `delete -f e2e.yaml --all -y` exit 0 and none of the files' entries are on the node.
- **Wrong kube context refused.** A variant with `kube_context: kind-other`: `diff`, `apply -y`, `delete --all -y` each raise a `ClickException` that names both contexts. Backend state is identical before and after. (The variant never changes the real kubectl context.)
- **Cross-file reference blocked, then resolved.**
  - With none of e2e.yaml's entries on the node: `diff -f second` has blocked rows for QaTwo and QaThree; `apply -f second -y` exits 1 and creates nothing.
  - Apply e2e.yaml; `diff -f second` shows `+` for both projects and the dataset and repository rows as "on the node, not in this file".
  - `apply -f second --project QaTwo -y` creates QaTwo only. `apply -f second -y` adds QaThree. Both have the dev project's dataset and repositories.

Not repeated here because the unit tests already cover them with a fake backend: the plan format, the loader errors, the ordering, `--project` limiting.

## 5. Ordered steps

Runtime base: failure suites about 35 min. The nodefile times are estimates, measure on the first run (`--durations=0` is already on).

1. **Batch the six missed-PR checks. Size S. Tests only. Saves about 4.5 min.**
   - Today the 5-tick wait after each switch-on lets a late catch-up settle before the next group records its counts. Without it, a replay from group N lands inside group N+1's off window.
   - So the off-window checks stop comparing global (PRs, tasks) counts. Each group asserts on its own PR number: no task for it, and no trigger where the group claims that. Only the revoked trigger resource group claims no trigger today (`assert_counts`). The other five check tasks only (`assert_no_new_task`).
   - Each group records its missed PR number and does not wait after switching back on.
   - One test after the six groups does one `quiet_wait(QUIET_TICKS)` and re-checks every missed PR with the same claim, plus one guard: the task count equals the count at the start.
   - The guard's failure message lists the six PR numbers and which of them has a task, so a replay is attributed to its group.
   - Detection is not weaker (later groups run through more ticks after an earlier switch-on). Attribution is: the guard names the PR, not the tick.
2. **conftest helpers. Size S. About +10 s per suite.**
   - `PROJECT` and `SECOND_PROJECT` from the node files; `Fncli.output`, `Fncli.refused`, `plan`; `variant`; `assert_in_sync`; the kube-context and `.dev.env` preflight.
   - `assert_in_sync` after setup and before the final teardown of each suite.
3. **fncli: `delete --gitea`, slim e2e-second-projects.yaml. Size S.** `delete_gitea_leftovers` is removed from `TEARDOWN_STEPS`. Unit tests for the new rows. A run of the happy path confirms the cleaner teardown.
4. **The nodefile suite (section 4). Size M. Adds a suite of about 5 min, run first.** Registered in dagster/conftest.py. After this step a broken `diff`, `apply` or `delete` fails in minutes.
5. **fncli: `--project` on the eight commands, `secret-set LABEL`, `delete-gitea-token --app`. Size M to L.** One shared loader, unit tests per command. No e2e change yet, so nothing breaks while it lands.
6. **Rewire the suites to the new options. Size M. Runtime neutral.** Remove every `TEST_*`, `DEFAULT_PROJECT_DATASET` and `GITEA_TOKEN_NAME` read from tests and conftest. Drop the "keep them equal" comment in e2e.yaml and the e2e `TEST_*` lines from the README preflight. The suite then runs with only the cluster addresses in `.dev.env`.
7. **Docs. Size S.** README: the nodefile suite in the table, the admin login (the `keycloak-first-user` secret, not `FNCLI_ADMIN_*`), the node block as the cluster pin, the new `delete --gitea`.
8. **Optional, later.** `diff` reads Gitea so a no-op shows `=` and prints "Nothing to do". `FNCLI_NODE_FILE` for the backend address of every command.

Order logic: 1 to 3 need no fncli work beyond a small flag and save time or remove hand cleanup now. 4 adds the coverage of the new commands. 5 and 6 are the larger change that removes the second source of truth and can wait until 1 to 4 are green.
