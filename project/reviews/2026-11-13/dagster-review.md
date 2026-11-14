# Dagster side review (second pass)

Read-only, time-boxed. Paths are under `dagster/app/`. "Confirmed" means read in the code; "inferred" means it depends on code I did not open (nexus-api, Dagster internals).

## Bugs

### 1. One project's failing repository list kills the evaluate tick for every project (confirmed)
- `definitions/sensors/git/pr_evaluate.py:30-32` (`items`), `definitions/sensors/base.py:117-128` (`LaunchingSensor.__call__`)
- The per-item `try` wraps only `in_flight`, `ready` and `run_request`. The `for item in self.items()` step is outside it, and `items()` calls `get_project_trigger_repositories(project.id)` lazily per project. If that call raises for one project, the generator raises out of the sensor.
- Dagster drops what a failing tick yielded (the class's own docstring says so), so the projects before it lose their runs too, every tick, until that one project is fixed.
- Change: have `items()` yield per project inside the same failure handling the items get (collect the project in `failed` and go on), as `__call__` already does for items. The ingest sensor uses the same base, so check its `items()` for the same shape.

### 2. A QUEUED or RUNNING task whose run no longer exists stays that way forever (confirmed)
- `definitions/sensors/task/reconcile.py:57` (`if not runs or ...: return 0`)
- The docstring only means to leave alone a PENDING task without a run (the launcher owns it). The code leaves alone any unfinished task without a run. A QUEUED or RUNNING task whose run was deleted in the Dagster UI, or lost with the run storage, is never moved: the launcher only takes PENDING, run-status sensors have no run to react to.
- Change: this is a decision, so it belongs to nexus-api: report "no run for this attempt" to it and let it fail the task (or re-pend it). Do not decide in the sensor.

### 3. A permanent error in `_launch` retries every tick forever, task stuck PENDING (confirmed for the code path; which inputs trigger it is inferred)
- `definitions/sensors/task/launcher.py:31-35` and `:60-70`
- Every exception from `_launch` is logged and "retried on the next tick". That is right for a failed HTTP call, wrong for errors that cannot go away: `build_run_config` raising a pydantic error (`run_config.py:32-38`, e.g. a dataset field `PipesDatasetConfig` refuses), or `dg.RunRequest` refusing a non-string tag value from `spec.tags` (`models/task_spec.py:12` types it as bare `dict`).
- The task then sits PENDING with one log line per tick and nobody is told.
- Change: build the run request from data nexus-api has already validated to the same shape (tags `dict[str, str]`, dataset fields), and type the Dagster models to match so a mismatch fails at parse. If a launch still cannot be built, tell nexus-api so it fails the task with the cause, as it does for its own "fail" outcome.
- Inferred, not checked: if Dagster rejects the run config when submitting the run (after the sensor has returned), the tick fails for all tasks in it, not only the bad one.

### 4. ODBC connection string is built without quoting the password or user (confirmed)
- `definitions/pipes.py:273-279` (`_get_conn_str`), used at `:251`
- `Pwd=$(DB_PASSWORD);` is expanded by the kubelet as-is. A password containing `;`, `{` or `}` cuts the string short or adds attributes (`x;Server=other`), so the task cannot connect, or connects elsewhere.
- Change: wrap the values in braces and double any `}` (ODBC quoting). The kubelet expansion makes that impossible in the pod spec, so the clean fix is for nexus-api to put a ready `CONNECTION_STRING` key in the run's Secret, which also removes the driver table from Dagster.

### 5. Spec file path goes into the provider URL unquoted (confirmed)
- `github.py:90`, `gitea.py:96` (`f"repos/{repo_path}/contents/{file_path}"`), fed from `definitions/sensors/git/pr_parser.py:58-62`
- The file name is chosen by the PR author. A name with `#` or `?` (legal in git) truncates the path or adds query parameters, so the fetch 404s or reads a different path. A 404 raises, the op retries 3 times, the run fails, and the evaluate sensor relaunches it every retry interval forever with the PR stuck UNKNOWN, blocking nothing else but never ending.
- Change: `urllib.parse.quote(file_path)` at both call sites.

### 6. Empty or oversized spec file is sent on as an empty spec (confirmed for the code; provider behaviour from memory)
- `gitea.py:99-102`: with no `content` key it returns `""`; if the path is a directory the response is a list and `.get` raises `AttributeError`.
- `github.py:93-94`: GitHub returns `content: ""` for files over 1 MB, which decodes to `""`.
- The PR is then READY with an empty `spec_raw` and the rejection cause the user sees is about an empty spec, not the real reason.
- Change: in `gitea.py` use `data["content"]` like `github.py` (fail fast); let nexus-api name "empty spec file" as the cause.

## Security

### 7. Spec env is passed to the pod with keys upper-cased, no reserved names (confirmed)
- `definitions/pipes.py:108-121` (`_setup_env`), `:302-303` (`_dict_to_pod_env`)
- Not exploitable as far as I read: `ARTIFACT_PATH`, `CONFIG_PATH`, schema names and the `DB_*` entries are all placed after the spec's, and the last duplicate wins in Kubernetes. But it holds only by list order, and `.upper()` means `cdm_schema` and `CDM_SCHEMA` from a spec become two entries with the same name.
- Change: none needed in Dagster if nexus-api validates env names when it parses the spec (inferred, not checked). Drop the `.upper()` so the pod gets what the spec said.

### 8. `compute` reaches the container `resources` unvalidated on the Dagster side (confirmed here, nexus-api side inferred)
- `definitions/pipes.py:225-226`, `models/task_spec.py:11`, `run_config.py:20`
- `compute` is a bare `dict` end to end and is assigned whole to `containers[0].resources`. It is limited to that one field, so it cannot add volumes or privileges, but limits and requests are whatever the spec says. Whether nexus-api caps them I did not check.
- Change: none in Dagster; confirm nexus-api validates `compute` against a schema with caps.

### 9. SSRF via provider URLs: nothing found (confirmed)
- `definitions/sensors/git/base.py:44-49` builds clients from `repo.provider.api_uri`, which nexus-api supplies and an admin sets. `utils.py:60` joins it with a path. No PR-supplied value reaches the host part. The only PR-supplied URL piece is the file path in item 5.

## Improvements

### 10. Model defaults hide missing fields (confirmed)
- `models/task.py:14` (`status: str | None = None`), `models/task_spec.py:11-13` (`compute`, `tags` default `{}`), `models/trigger_repository.py:45,49` (`pr_count = 0`, `pull_requests` default empty)
- `reconcile.py:60` compares `task_status.value == task.status`: with `status` missing it is `None`, so every tick patches. An empty default for `pull_requests` reads as "no PRs" if the API stops sending the field. All models also set `extra="allow"`, so renamed fields pass silently.
- Change: make the fields the sensors act on required (`status`, `tags`, `compute`, `pull_requests` where used).

### 11. `image_pull_secret` is dead (confirmed)
- `definitions/pipes.py:49,88,227-228` read it; `run_config.py:17-24` (`K8sPipesOpConfig`) never sets it and nothing else in `dagster/app` does.
- Change: delete it from the op, or carry it from the launch decision if private task images are meant to work.

### 12. Dagster owns the dataset-type to ODBC driver table (confirmed)
- `definitions/pipes.py:35-40,273-279`. An unknown type is a `KeyError` in the run after nexus-api already decided to launch. See item 4: moving the connection string to nexus-api fixes both.

### 13. Chmod failures on the run folder are swallowed (confirmed)
- `definitions/pipes.py:196-202`. Deliberate for CIFS per the comment, but on other backends a failed chmod shows up later as the task being unable to write results, with no log line. Log the `OSError` at warning.

## Checked, fine
- Double launch: run key `task/<id>/<attempt>` plus the backend's 409 on non-PENDING; the launcher tick is safe to repeat.
- User tags cannot shadow `fn/` or `dagster-k8s/config` (`launcher.py:63`).
- Task pod: no service account token, only its own run folder mounted, deadline plus grace matches `pod_wait_timeout`.
- Lost or hung run pod: `runMonitoring.maxRuntimeSeconds` in `k8s/federated-node/values.yaml:456-461` fails the run, then the failure sensor and reconcile move the task.
- Evaluate job: 400 and 409 from the backend are handled as outcomes; ops are safe to repeat.

## Not covered
- `utils.py` beyond the request method (token refresh and retry adapter), `models/dataset.py`, `run_record.py`, `results_repository.py`.
- `base_branch` and `target_dir` reaching git commands in `delivery/` (earlier review covered `git_push.py` arguments).
- `pr_ingest.py` and `ingest_job.py` beyond what the earlier review reported; whether ingest `items()` has the same problem as item 1.
- The nexus-api side of items 3, 7 and 8 (what it validates).
- Dagster's behaviour on an invalid run config at submit time (item 3, inferred).
