# 0002. TaskSpec, and a Task derived from spec and trigger

## Context

The API request body is TES-like (image and env on the first executor), the pull request spec file is flat (`image` or `docker_image`). The run needs one shape, and delivery needs to reproduce what was run.

## Decision

- The trigger keeps the spec exactly as received in `spec_raw` (the pull request spec file, or the API request body, max 64 KiB), before anything is parsed. A spec that fails validation rejects the trigger, which keeps `spec_raw`. `spec_raw` is never returned by the API.
- `TaskSpecRequest` (pydantic, `extra="forbid"`) is the one normalised description: `name`, `image`, `env`, `params`, `dataset`, `tags`, `resources`, `repository`. `from_api_body` and `from_pr_spec` build it from the two shapes, and it validates the image length and the env (key format, reserved keys, size). The pull request spec file is JSON with a flat `spec` object.
- A `Task` is created from a spec and its trigger. What it runs is stored in its own table, `task_specs` (`image`, optional `dataset_id`, `env`), referenced by `tasks.task_spec_id`; `name` and `params` stay on the task.
- Dagster sends the spec file as read to the backend, which parses and validates it: a 400 there means the backend has already marked the trigger `REJECTED`.
- The launcher builds the run config from `task.spec` and the dataset, if the spec has one (`build_run_config`). The spec is written to `spec.json` on delivery ([0013](0013-results-delivered-as-branch-and-pull-request.md)).
- The dataset a spec names must be one assigned to the project and active; with none named, the project's default dataset is used ([0006](0006-global-resources-and-project-resources.md)).

## Consequences

- An unknown field in a spec is an error, not silently dropped.
- Editing a spec file after merge changes nothing: the task keeps the spec read at the merge commit.
- A task also stores a snapshot of the configuration it was created under ([0009](0009-task-pinned-to-its-configuration.md)).

## Alternatives considered

- **Store only the trigger payload and re-derive at launch:** the API and PR shapes would leak into the launcher.
- **Dagster creates tasks without backend validation:** the backend knows datasets and images.
