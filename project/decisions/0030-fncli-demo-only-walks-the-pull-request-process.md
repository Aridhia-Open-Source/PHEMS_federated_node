# 0030. fncli demo only walks the pull request process

Status: Accepted, 2026-11-09.

## Context

`fncli demo` set a project up, walked a pull request through it and tore it down again, one confirmed step at a time. The set-up and tear-down steps were a second copy of what the setup commands did, and `apply` and `delete` ([0025](0025-fncli-bootstrap-files-diff-apply-delete.md)) now do that from a file. Two paths to the same state drift apart. A demo that fails half way also left its set-up behind, with no way to run only the part that failed, and the demo could not be repeated without a teardown first.

## Decision

`fncli demo -f FILE [--project P]` demonstrates the pull request process on a node that `apply` has already set up, and creates and deletes nothing.

- **It first proves the node matches the file.** It builds the plan `diff` shows. If any row would change, it stops with exit 1 and lists the rows; the person runs `apply`. Nothing is applied for them.
- **Then it checks and walks, one confirmed step at a time:** the dataset healthcheck, the git token and project checks, a pull request into the trigger repository, the task it becomes, and the results pull request.
- **Set-up and clean-up are `apply` and `delete`.** The flow is `apply`, then `demo` (as often as wanted), then `delete`. The dataset the project is assigned is not in the file: an experiment made it ([0028](0028-experiments-own-their-database-seed-image-and-dataset-file.md)) and the plan resolves it against the node ([0027](0027-bootstrap-files-split-by-stage-of-use.md)).

## Consequences

- The demo can be repeated on the same node, and a failed run leaves the node as it was set up, and `--from N` retries from the failed step.
- One set-up path for the demo, the e2e suites and a person at a terminal, so what the demo shows is what the others use.
- The demo tells the audience, by the diff check, that the node is what the file says before it shows the pull request process.
- A demo needs two commands before it, `apply` and (once) the experiment's `setup`, which is more to type than the old single command.
- The demo's pull requests and results stay in the git host and in the node until the project is deleted; `delete` leaves the Gitea repositories ([0026](0026-apply-is-additive-delete-is-a-soft-delete.md)).

## Alternatives considered

- **Keep set-up and tear-down in the demo:** two paths to the same state, and a demo that cannot be repeated.
- **Run `apply` for the person when the diff shows a change:** the demo would write to the node on its own, and what it presents as "the node as set up" would be whatever it had just changed.
- **No check of the node:** a demo on a half-configured node fails at a later step with a message about a task, not about the missing set-up.
