# 0002. TaskSpec, and a Task derived from spec and trigger

## Context

The API request body is TES-like (image and env on the first executor), the pull request spec file is a small JSON object (`spec` and `metadata`). The run needs one shape, and delivery needs to reproduce what was run.

## Decision

- The trigger keeps the spec exactly as received in `spec_raw` (the pull request spec file, or the API request body, max 64 KiB), before anything is parsed. A spec that fails validation rejects the trigger, which keeps `spec_raw`. `spec_raw` is returned only by the task trigger response, below.
- `TaskSpecRequest` (pydantic, `extra="forbid"`) is the one normalised description. `from_api_body` and `from_pr_spec` build it from the two shapes, and it validates the image length, the env (key format, reserved keys, size), the tags and the config.
- The pull request spec file is JSON: `spec` (required) and `metadata` (optional) are the only top-level keys. In `spec`, `image` is required and `dataset`, `env`, `tags` and `config` are optional. Any other key, at either level, rejects the pull request. `metadata` is any JSON value, not validated. `name`, `params`, `repository`, `resources` and the `docker_image` alias are API-only (the API's resources are validated but not stored).
- `env` keys are compared upper-cased and are rejected if reserved: `ARTIFACT_PATH`, `CDM_SCHEMA`, `WRITE_SCHEMA`, `DB_USERNAME`, `DB_PASSWORD`, `CONNECTION_STRING`, `CONFIG_PATH`, or a `DAGSTER_` or `KUBERNETES_` prefix. The list is one backend constant (`TASK_ENV_RESERVED_KEYS` and `TASK_ENV_RESERVED_PREFIXES`); Dagster does not re-check it.
- `tags` are text to text, copied onto the task's run by Dagster. A key has to match `TASK_TAG_KEY_REGEX` (1 to 63 letters, digits, `_`, `.` or `-`), otherwise the pull request is rejected: Dagster stores them as `user/<key>` and takes no further `/`. `config` is a JSON object, its contents unchecked.
- A `Task` is created from a spec and its trigger. What it runs is stored in its own table, `task_specs` (`image`, optional `dataset_id`, `env`, `tags`, optional `config`, optional `metadata`), referenced by `tasks.task_spec_id`; `name` and `params` stay on the task. A pull request task is named `<project name>:PR#<pull request number>` and has no params.
- The task trigger response (`GET /projects/{id}/tasks/{task_id}/trigger`) carries `spec_raw`, the spec file as received. Delivery writes it as `spec.json` ([0013](0013-results-delivered-as-branch-and-pull-request.md)), so the client's `metadata` rides along. The task response carries `project_name` and `dataset_name` (the dataset actually used).
- Dagster sends the spec file as read to the backend, which parses and validates it: a 400 there means the backend has already marked the trigger `REJECTED`.
- The launcher builds the run config from `task.spec` and the dataset, if the spec has one (`build_run_config`). The spec is written to `spec.json` on delivery ([0013](0013-results-delivered-as-branch-and-pull-request.md)).
- The dataset a spec names must be one assigned to the project and active; with none named, the project's default dataset is used ([0006](0006-global-resources-and-project-resources.md)).

## Consequences

- An unknown field in a spec file is an error, not silently dropped.
- Editing a spec file after merge changes nothing: the task keeps the spec read at the merge commit.
- A task also stores a snapshot of the configuration it was created under ([0009](0009-task-pinned-to-its-configuration.md)).

## Alternatives considered

- **Store only the trigger payload and re-derive at launch:** the API and PR shapes would leak into the launcher.
- **Dagster creates tasks without backend validation:** the backend knows datasets and images.
