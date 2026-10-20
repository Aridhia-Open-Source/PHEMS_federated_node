# 0021. Responsibility: the webserver owns the record and the rules; Dagster carries out decisions

## Context

Dagster polls, starts runs and watches them; the webserver stores the state. Rules about what may run, such as whether a dataset link is active, could be written on either side. A rule held in both drifts, and a rule held in Dagster cannot be tested or changed with the data it reads.

## Decision

- The webserver owns the record and every rule. It is the only writer of the state, through its state tables ([0005](0005-state-transition-tables.md)).
- Dagster owns doing the work: polling, starting runs, watching them, and git. It holds no copy of the rules.
- Dagster asks and acts; it does not decide. Facts go from Dagster to the webserver (a run started, a run failed) and decisions come back as typed outcomes: launch, wait or fail, with a cause for fail. A status code means only whether the call worked, never what was decided.
- A call repeated each tick is safe: a decision is computed from the current state, and a write that repeats is refused or ignored by the state tables.
- The dependency is one way: Dagster calls the webserver; the webserver never calls Dagster.

The task launcher follows it, with one call per pending task: `POST /projects/<id>/tasks/<id>/launch`. The webserver computes the decision with `decide_launch` in `webserver/app/helpers/task_config.py`. The first rule that applies decides, in this order: something the task uses is revoked or deleted, its pinned configuration changed ([0009](0009-task-pinned-to-its-configuration.md)), its dataset link is not active, its dataset's secret is disabled ([0008](0008-enabled-revoked-and-soft-delete.md)). On `fail` the webserver moves the task to `FAILED` with the cause itself, through its state tables, and answers `outcome` and `cause`. On `launch` it writes nothing and answers the task and its dataset, what the run request is built from. A task that is no longer `PENDING` is a 409 and the launcher skips it. The launcher checks nothing itself and writes nothing. `GET /projects/<id>/tasks/<id>/config` returns the same decision read-only, with the facts behind it, for delivery and display.

## Consequences

- A rule changes in one place, with its tests next to the data it reads.
- The launcher's tests mock the answer and check that it does what the outcome says.
- The launcher makes one request per pending task, for the decision, the transition and the run inputs alike, after one `GET /tasks` that lists the tasks of all enabled projects: the webserver filters by status and by the project's `enabled` flag, so a tick makes one list request instead of one per project.
- Each tick costs the webserver the rule queries for every pending task. A task stays pending for a few ticks, so at the expected number of projects and tasks this is small.
- The decision and the transition are one call, but state can still change before the run is created. This is the design: the pipeline is event-driven and reconciling, and every actor acts on a view of the state that may already be stale. What keeps it safe is that every write goes through the state tables, which refuse an invalid move; delivery checks again before publishing, so a run started just after a revoke publishes nothing; and a retry re-evaluates from the current state. At worst a task runs against a setup that has just changed and fails or is not delivered, or fails when it could have run. No lock is planned, because one would narrow the window without closing it.
- A task failed by a rule stays failed until it is retried; there is no automatic re-evaluation.
- `get_task_config` returns the answer as a plain dictionary because delivery reads it too; the launcher's `launch_task` parses the launch answer into a model.

## Alternatives considered

- **Rules in the launcher, reading facts from several endpoints:** the rules drift from the record and are tested against mocks.

## Open questions

- Delivery should follow the same pattern: a deliver decision from the webserver, with Dagster pushing and reporting.
