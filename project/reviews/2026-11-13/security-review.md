# Security review: Federated Node (branch dagster-develop)

Time-boxed (8 minutes), read-only, grep-driven. Only a part of the code was read; see "Not covered" at the end.
Each finding says what was confirmed in the code and what was not.

## 1. POST /projects/{id}/tasks has no project-level authorisation (medium to high, exploitability partly unconfirmed)

- `nexus/api/app/tasks_api.py:246-298` (`post_tasks`), `nexus/api/app/models/task.py:110-170` (`Task.validate`)
- Confirmed: the route only requires the Keycloak scope `can_exec_task`. Nothing ties the caller to `project_id`.
  `Task.validate` resolves the project from the path, then picks the named dataset or the project's default
  (`project.resolve_dataset`). The data access request check is switched off (`TODO(DAR)` at `models/task.py:150`
  and `helpers/wrappers.py:37`).
- Confirmed: there is no image allow-list. The comment at `models/task.py:117` mentions one, but the only image check
  is the format regex in `validate_image_format` (`models/task.py:171-173`). A grep for an allow-list in `nexus/api/app`
  and `dagster/app/definitions` finds nothing.
- Confirmed: the task pod gets the dataset's `DB_USERNAME`, `DB_PASSWORD` and `CONNECTION_STRING` in its env
  (`dagster/app/definitions/pipes.py:244-253`).
- Exploit scenario: any user holding `can_exec_task` posts a task to another project's id with an image they control
  from any registry. If that task launches, their code runs with that project's dataset credentials.
- NOT confirmed: which roles hold `can_exec_task` (policy is in `k8s/federated-node/scripts/realms.json:210,315,369`,
  not read), and whether an API-created task is launched by Dagster at all (the launcher sensor was not read; the API
  trigger may be legacy). What the task can send out depends on `templates/task-network-policy.yaml`, also not read.
- Suggested fix: check the caller against the project (membership or the DAR check) in `post_tasks` and
  `post_tasks_validate`, and enforce a per-project image/registry allow-list in `Task.validate`.

## 2. Image format regex accepts a trailing newline and any registry (low)

- `nexus/api/app/models/task.py:172-173`
- Confirmed: `re.match(r'^...$', image)`; `$` matches before a final `\n`, so `repo/img:tag\n` passes. The value goes
  to the pod spec as `image` (`dagster/app/definitions/pipes.py:87,137`).
- Impact: Kubernetes most likely rejects the pod, so this is a failed task, not an injection. Not tested.
- Suggested fix: `re.fullmatch`.

## 3. Dead SQL validator runs raw user SQL, without read-only on MSSQL (low, not reachable today)

- `nexus/api/app/helpers/query_validator.py:45-58`
- Confirmed: `validate()` runs the query text as-is; Postgres gets `SET TRANSACTION READ ONLY`, MSSQL gets nothing.
- Confirmed: no caller in `nexus/api/app` (grep). Not exploitable now; it becomes a write path into datasets if it
  is wired up again.
- Suggested fix: delete the module.

## 4. Task owner check falls back to "any system or admin", project scope only by id match (informational)

- `nexus/api/app/tasks_api.py:62-73` (`does_user_own_task`)
- Confirmed: read routes for a task (`get_task_id`, `get_task_trigger`, `get_task_config`, `get_task_results`,
  `results_api.get_result`) all check the task belongs to the path's project and that the caller is the requester,
  an admin, or the system user. No IDOR found on these.

## Checked and found sound

- Route auth coverage: every router or route in `nexus/api/app/*_api.py` carries `require_scope(...)`, except
  `main.py` (index, ready/health check, login, refresh_token). State-changing pipeline routes add `system_only`.
  Token minting (`POST .../token`, `results_repositories_api.py:55`, `trigger_repositories_api.py:117`) is `system_only`.
- Git push (`dagster/app/delivery/git_push.py`): `subprocess.run` with an argument list, no shell. The token goes in
  `http.extraHeader` through env, not in the URL or argv (`git_push.py:22-35`). Error text carries git's stderr only.
- Results packaging: `zip_dir` skips symlinks (`git_push.py:56-72`); the output directory is checked to stay inside
  the clone (`dagster/app/delivery/results.py:190-191`).
- No `shell=True`, `yaml.load`, `pickle`, `verify=False`, `extractall` or f-string SQL in `nexus/api/app` or
  `dagster/app` (tests excluded).
- Task pod spec: `automountServiceAccountToken: False`, security contexts set (`pipes.py:205-231`). Their content
  (`PipesSecurityContextConfig`) was not read.
- Chart: no literal passwords found in `values.yaml` by grep; Roles are namespaced, secrets verbs limited to
  get/create/patch/delete; NetworkPolicy templates exist for tasks and internal traffic.

## Not covered

- Keycloak policy (`realms.json`): who holds which scope. Finding 1's severity depends on this.
- `is_token_valid` body and `_access_from_refresh` in `helpers/keycloak.py` (only partly read).
- `secrets_api.py`, `datasets_api.py`, `projects_api.py` handler bodies and the secret/dataset DTOs (secret values in
  responses not checked beyond the route list).
- `helpers/git_tokens.py`, `helpers/task_resources.py`, `helpers/kubernetes.py`, `helpers/git_uri.py`.
- Dagster sensors (`definitions/sensors/`), `github.py`, `gitea.py`, `backend.py`: pull request content handling,
  SSRF through provider URIs, the launcher path.
- Git argument injection through `base_branch` / `target_dir` values starting with `-` (admin-set; validation in the
  DTOs is `min_length=1` only, the git call sites were not traced end to end).
- Helm templates in detail: `task-network-policy.yaml` egress rules, container securityContext on the deployments,
  env literals, Gitea and Postgres defaults.
- `nexus/ui`, `fncli`, `pypipes`, `build/`.
