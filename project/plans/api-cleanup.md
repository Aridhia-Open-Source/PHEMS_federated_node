# API cleanup: plan, steps, propagation

Decisions are in `api-cleanup-decisions.md`. This file is how to carry them out.

## The plan in short
The API keeps only API work: routes, request handling, permission checks, and logic over its own database models. Anything that talks to an outside API (git, Kubernetes, Keycloak) and stands alone lives in fednode's client for it. The `tasks/` and `repos/` folders disappear: their logic becomes methods on models, shared models in fednode, or one small helper. Dead copies go. Error codes follow the HTTP spec.

| Today (API) | After |
|---|---|
| `tasks/task_config` | `task.config` methods on the Task model |
| `tasks/compute`, `tasks/limits` | fednode `TaskCompute` (renamed from `TaskResources`) + `TaskComputeLimits` settings; API request field `compute` |
| `tasks/task_resources` | `RunResources` class in `app/clients/` |
| `tasks/spec_files` | `ProjectTriggerRepository.spec_files(pull_request)` |
| `repos/pull_request_fanout` | methods on `PullRequest`, `TriggerRepository`, `ProjectTriggerRepository` |
| `repos/repository_loop` | `Project.check_results_dir_not_watched()` (per project only) |
| `repos/git_tokens` | `app/helpers/git.py` (token cache) + `require_token_allowed` on the repository model |
| `clients/kubernetes`, `kubernetes_names` | deleted; API uses fednode directly, errors mapped in `errors.py` |
| `KeycloakError`, `KubernetesException` | fednode `ClientError` subclasses (`KubernetesError`) |
| validation errors 400 | 422 (400 only for unreadable bodies) |
| `JsonObjectBodyMiddleware` | removed; routes take request models |
| 10 dead top-level `*_api.py`, stale `tasks/resources.py` | deleted |
| `clients/keycloak`, `helpers/wrappers` | parked until after auth |

## Where each change is made
Most of it lands in **#806** (fednode stack, between #696 and #766), because those files already exist there. Three things only exist higher up and are fixed in the PR that adds them:
- Settings (`TaskLimitsSettings` -> `TaskComputeLimits`): **#742** (unified settings creates `settings/`; at #806 limits are still in `helpers/const.py`).
- Stale `tasks/resources.py`: **#742** (adds it).
- Dead router copies: **#682** and **#686** (their "restore" commits re-add them).

## Steps (one subagent each, in order, all on #806 unless stated)
Every step is reviewed as its own PR: steps 1–3 each branch off #806's branch (`refactor/api-onto-fednode`) and PR into it; steps 4–5 branch off #742 / #682 / #686 after the rebuild and PR into those branches. Draft PR, xo card in Review, codepint reviews and merges (squash). One commit per step PR, tests only for files changed, progress lines `[cleanup-N]` in `.claude/plans/2026-11-26-stack-fix.progress.txt`. Read only lines around grep hits.

### Step 1 (#806): dissolve `tasks/`
1. `task_config` -> methods on `models/task.py` (`snapshot()`, `snapshot_hash()`, `config_changes()`); repoint callers (`git grep -n 'task_config'`).
2. fednode `clients/nexus/models/task_resources.py` -> `task_compute.py`, class `TaskCompute`; move `tasks/compute.py` checks into it as field/model validators; limits check reads `info.context["limits"]` only when present. Rename every use (`git grep -n 'TaskResources'` in nexus, dagster). Dagster `definitions/pipes.py` reads `spec.compute`.
3. API create-task request body field `resources` -> `compute: TaskCompute`; validate with `context={"limits": <limits from helpers/const.py at this level>}`. Update fncli/demo task bodies and tests that send `resources`.
4. `tasks/task_resources.py` -> `app/clients/run_resources.py`, class `RunResources(task, run_id)` with `create()` and classmethod `delete(run_id)`; routes build it.
5. `tasks/spec_files.py` -> `ProjectTriggerRepository.spec_files(pull_request)` + `is_under_dir` beside it; repoint `models/pull_request_trigger.py`, `repos/pull_request_fanout.py`.
6. Delete `tasks/`.
- Downstream conflicts: #742 (settings, `tasks/resources.py`, `projects/tasks_api.py`), #686 (`models/task.py`, `projects/tasks_api.py`), #685/#688 (`projects/tasks_api.py`).

### Step 2 (#806): dissolve `repos/`
1. `pull_request_fanout.py` -> `PullRequest.store()` (classmethod), `TriggerRepository.ingest()` + `.active_assignments`, `ProjectTriggerRepository.create_triggers()/unmatched_cause()/backfill()/skip_gap()`. Cross-model refs via the `models` ModelRegistry (`models/__init__.py`). Repoint routes.
2. `repository_loop.py` -> `Project.check_results_dir_not_watched()`: per project only, same git repo only, watch_dir vs target_dir overlap ('' = whole repo). Call it where a project's trigger or results repository is added/changed. Drop the cross-project query.
3. `git_tokens.py` -> `app/helpers/git.py` (`mint_token`); `require_token_allowed` -> repository model method (project part on the project's link).
4. Delete `repos/`.
- Downstream conflicts: #684 (`models/project.py`, `project_trigger_repository.py`, `trigger_repository.py`), #742/#685/#688/#682 (routers in `globals/`, `projects/`).

### Step 3 (#806): errors, Kubernetes wrappers, middleware
1. `KeycloakError`, `KubernetesException`->`KubernetesError` into fednode as `fednode.http.ClientError` subclasses; delete from `helpers/exceptions.py`; repoint.
2. Delete `clients/kubernetes.py`, `clients/kubernetes_names.py`; use fednode's client and name checks; in `errors.py` map name-check errors to 422.
3. `errors.py`: request validation 400 -> 422 (keep the path-id 404); update tests expecting 400.
4. Remove `JsonObjectBodyMiddleware` after converting any route that reads the raw body to a request model.
- Downstream conflicts: #683/#686/#742 (`clients/keycloak.py`), #682/#686 (`helpers/wrappers.py`), tests across auth/authz.

### Step 4 (#742, during propagation): settings + stale copy
- `TaskLimitsSettings` -> `TaskComputeLimits` in `fednode/settings.py` (all optional) with the API subclass required; `TaskCompute` validation context uses `settings.tasks.limits`. Delete `tasks/resources.py` (stale copy) — the plan's `RunResources` replaces it.

### Step 5 (#682, #686, during propagation): dead router copies
- For each of the 10 top-level `*_api.py`, diff the PR's edits in the dead copy against the live `globals/`/`projects/` router; carry missing hunks across; delete the dead copy in that PR.

## Propagation strategy (history may be rewritten)
1. **Make every PR one commit first.** Squash each open stack PR to parent + one commit (`git commit-tree <tip>^{tree} -p <parent>`, PR title as message, never an old message: they can carry `[skip ci]`). #686, #714, #696 currently have extra commits on top.
2. **Finish all #806 work before moving anything.** Steps 1–3 land on #806; nothing above moves until they're done, so the chain is rebuilt once.
3. **Write a codemod.** One script (`tmp/codemod.py`) with every rename and moved call from steps 1–3 (imports, `TaskResources`->`TaskCompute`, `ingest_pull_requests(id, x)`->`TriggerRepository...ingest(x)`, `spec_files(pr, d)`->`assignment.spec_files(pr)`, `resources`->`compute`, exception names, deleted modules). Most conflicts above are import and call-site lines, not logic.
4. **Rebuild bottom-up in one pass** (after step PRs 1–3 are merged into #806) (worktree `tmp/rebuild`, `rb/<branch>` refs, as the last rebuild):
   - For each PR from #766 upward: `cherry-pick -X theirs` its single commit onto the rebuilt parent, then run the codemod, then resolve what's left by hand with these rules: moved code wins in its new place; re-apply the PR's intent there; deleted files stay deleted unless the PR is the one that should delete them (steps 4–5 happen here).
   - `git rerere` on, so a retried resolution is replayed.
   - Expected hand-work only at: #742, #682, #683, #684, #686, #685, #688, #779 (#779 deletes the `helpers/` copies #806 already deleted: take the delete).
   - Import check after each PR (`pylint --disable=all --enable=E0401,E0611,E0602` on nexus/api and nexus/fednode), no tests.
5. **Review report before pushing:** `git range-diff old-parent..old-tip new-parent..new-tip` per PR, filtered to hunks the codemod didn't explain, written to `project/plans/api-cleanup-rebuild-report.md` for codepint; push only after an OK. Then raise step 4–5 PRs.
6. **Test once per stack top** (fednode, auth, authz, operator, flux): only the test files the cleanup touched.
7. **One atomic push** of all branches with `--force-with-lease`, each commit with a new line in `.github/ci-retrigger/pr-N.md`; CI runs once per PR.
8. Leaves (#776, #803) and stacks branching off below #806 are untouched.
