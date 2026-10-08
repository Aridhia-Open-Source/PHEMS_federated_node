# 0002. TaskSpec, and a Task derived from spec and trigger

- Status: Accepted

## Context

The API request body is TES-like (image and env on the first executor), the pull request spec file is flat (`image` or `docker_image`). The run needs one shape, and delivery needs to reproduce what was run.

## Decision

- `TaskSpec` (pydantic, `extra="forbid"`) is the one normalised description: `name`, `image`, `env`, `params`, `dataset`, `tags`, `resources`, `repository`. `TaskSpec.from_api_body` and `TaskSpec.from_pr_spec` build it from the two shapes.
- `Task` is created from a spec and its trigger. The spec is stored once in `tasks.spec` (JSON); `docker_image`, `name` and `dataset_id` are derived columns.
- The Dagster side validates the pull request file with its own `PullRequestSpec` (same fields, `extra="forbid"`, normalises `docker_image` to `image`). The backend validates again when it creates the task, and a 400 there turns the trigger into `REJECTED`.
- The launcher builds the run config from `task.spec` and the dataset (`build_run_config`). The same spec is written to `spec.json` on delivery ([0007](0007-results-delivered-as-branch-and-pull-request.md)).

## Consequences

- An unknown field in a spec is an error, not silently dropped.
- The spec is duplicated on the Dagster side (`PullRequestSpec` vs `TaskSpec`); the backend remains the authority.
- Editing a spec file after merge changes nothing: the task keeps the spec read at the merge commit.

## Alternatives considered

- **Store only the trigger payload and re-derive at launch**: rejected, the API and PR shapes would leak into the launcher.
- **Dagster creates tasks without backend validation**: rejected, the backend knows datasets and images.
